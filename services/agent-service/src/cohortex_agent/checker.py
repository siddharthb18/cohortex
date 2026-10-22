"""Evidence checker: deterministic code checks before any LLM judgment (ADR-008, FR-AGT-6/7).

Rules (contracts §6 numeric check rule, made precise here):

1. Every `NumberRef` must point at an evidence record of this investigation that is not a failed
   tool call, and `field` must resolve inside that record's `data` (paths like
   `series[0].afr_pct`, `items[2].failures`, `[0].drive_count`; a leading `data.` is allowed).
2. The resolved value must be numeric, and its unit, inferred from the field name, must equal the
   `NumberRef.unit`: `*_pct` -> pct; `failures`, `drive_count`, `drives`, `n_drives` -> count;
   `drive_days` -> drive_days; `age_days` -> days; `rate_ratio*` -> ratio; `p_value` -> p_value;
   anything else -> raw.
3. Tolerance: pct, ratio, p_value and raw match within 0.5% relative or 0.01 absolute; count,
   drive_days and days must match exactly.
4. Every number written in the claim text must be backed by one of the claim's `NumberRef`s, at
   the precision it is written ("2.3%" backs 2.3089). Dates, years, quarter labels, model names,
   SMART attribute IDs, a confidence level such as "95% CI" and a significance level such as
   "significant at 0.05" are not measured values and are skipped. "p < 0.01" is backed by any
   cited value below 0.01.
5. A claim must cite at least one evidence record or passage; every cited ID must exist.
   Evidence referenced by a `NumberRef` counts as cited and is added to `evidence_ids`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from cohortex_agent.schemas import Claim, DraftOutput, NumberRef

TOLERANT_UNITS = frozenset({"pct", "ratio", "p_value", "raw"})
EXACT_UNITS = frozenset({"count", "drive_days", "days"})
REL_TOL = 0.005
ABS_TOL = 0.01

_COUNT_FIELDS = frozenset({"failures", "drive_count", "drives", "n_drives"})
_PATH_TOKEN = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


class PathError(ValueError):
    pass


def infer_unit(field_path: str) -> str:
    leaf = re.sub(r"\[\d+\]", "", field_path).rsplit(".", 1)[-1]
    if leaf.endswith("_pct"):
        return "pct"
    if leaf in _COUNT_FIELDS:
        return "count"
    if leaf == "drive_days":
        return "drive_days"
    if leaf == "age_days":
        return "days"
    if leaf.startswith("rate_ratio"):
        return "ratio"
    if leaf == "p_value":
        return "p_value"
    return "raw"


def resolve_path(data: Any, path: str) -> Any:
    """Read a JSON path such as `series[0].afr_pct` from `data`."""
    path = path.strip()
    if path.startswith("data.") or path.startswith("data["):
        path = path[4:].lstrip(".") if path.startswith("data.") else path[4:]
    if not path:
        raise PathError("empty field path")
    position, current = 0, data
    while position < len(path):
        match = _PATH_TOKEN.match(path, position)
        if match is None or match.end() == position:
            raise PathError(f"malformed field path {path!r}")
        key, index = match.group(1), match.group(2)
        if key is not None:
            if not isinstance(current, dict) or key not in current:
                raise PathError(f"{path!r}: no key {key!r}")
            current = current[key]
        else:
            i = int(index)
            if not isinstance(current, list) or i >= len(current):
                raise PathError(f"{path!r}: index [{i}] out of range")
            current = current[i]
        position = match.end()
    return current


def values_match(unit: str, claimed: float, actual: float) -> bool:
    if unit in EXACT_UNITS:
        return claimed == actual
    diff = abs(claimed - actual)
    return diff <= ABS_TOL or diff <= REL_TOL * abs(actual)


# ------------------------------------------------------------------------------ text numbers


@dataclass(frozen=True)
class TextNumber:
    raw: str
    value: float
    decimals: int
    comparator: str  # "", "<", "<=", ">", ">="


_WORD = re.compile(r"\S+")
_NUMBER = re.compile(r"^(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)$")
_LETTER_PREFIX = re.compile(r"^[A-Za-z]{1,2}(?P<op><=|>=|[<>=≤≥])(?P<rest>.+)$")  # p<0.01, n=12
_STRIP = "()[]{},;:\"'`*_!?"
_COMPARATORS = {"<": "<", "≤": "<=", "<=": "<=", ">": ">", "≥": ">=", ">=": ">=", "=": ""}
_EXEMPT_PREVIOUS = frozenset(
    {
        "smart",
        "attribute",
        "attributes",
        "attr",
        "id",
        "section",
        "sections",
        "table",
        "figure",
        "fig.",
        "page",
        "step",
        "task",
        "q",
        "top",
    }
)
_CONFIDENCE_NEXT = ("ci", "confidence", "interval", "conf")
_SIGNIFICANT = frozenset({"significant", "significance", "significantly"})
_ALPHA = frozenset({"alpha", "alpha=", chr(0x3B1), chr(0x3B1) + "="})  # Greek small alpha
_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _is_year(raw: str) -> bool:
    return raw.isdigit() and len(raw) == 4 and 1990 <= int(raw) <= 2100


def _parse_token(part: str, previous: str, first: bool) -> tuple[str, str] | None:
    """(comparator, numeric text) for a word part, or None when it is not a plain number."""
    token = part.lstrip(_STRIP).rstrip(_STRIP + ".")
    comparator = ""
    prefixed = _LETTER_PREFIX.match(token)
    if prefixed:
        comparator, token = _COMPARATORS[prefixed.group("op")], prefixed.group("rest")
    else:
        for symbol in ("<=", ">=", "<", ">", "≤", "≥"):
            if token.startswith(symbol):
                comparator, token = _COMPARATORS[symbol], token[len(symbol) :].strip()
                break
        if not comparator and first and previous in _COMPARATORS:
            comparator = _COMPARATORS[previous]
    token = token.rstrip(".").removesuffix("%").removesuffix("\u00d7").removesuffix("x")
    token = token.removeprefix("~").removeprefix("≈").removeprefix("#").removeprefix("$")
    match = _NUMBER.match(token)
    return (comparator, match.group("num")) if match else None


def extract_text_numbers(text: str) -> list[TextNumber]:
    """Numbers stated in claim text that the checker must see backed by a `NumberRef`."""
    words = _WORD.findall(text)
    found: list[TextNumber] = []
    for index, word in enumerate(words):
        previous = words[index - 1].lower().strip(_STRIP) if index else ""
        before = words[index - 2].lower().strip(_STRIP) if index > 1 else ""
        following = words[index + 1].lower().strip(_STRIP) if index + 1 < len(words) else ""
        if _DATE.match(word.strip(_STRIP + ".")) or previous in _EXEMPT_PREVIOUS:
            continue
        if previous in _ALPHA or (previous == "at" and before in _SIGNIFICANT):
            continue  # a significance level ("significant at 0.05"), not a measured value
        # Ranges such as 0.2-1.4 (hyphen or en/em dash) are two numbers.
        parts = re.split("(?<=\\d)[\u2013\u2014/-](?=\\d)", word)
        for position, part in enumerate(parts):
            parsed = _parse_token(part, previous, position == 0)
            if parsed is None:
                continue
            comparator, raw = parsed
            if _is_year(raw):
                continue
            is_pct = part.rstrip(_STRIP + ".").endswith("%")
            if is_pct and not comparator and following.startswith(_CONFIDENCE_NEXT):
                continue  # "95% CI" names a confidence level, not a measured value
            mantissa = re.split(r"[eE]", raw)[0]
            decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
            found.append(TextNumber(raw, float(raw.replace(",", "")), decimals, comparator))
    return found


def text_number_backed(number: TextNumber, refs: Iterable[NumberRef]) -> bool:
    for ref in refs:
        v = ref.value
        if number.comparator == "<" and v < number.value:
            return True
        if number.comparator == "<=" and v <= number.value:
            return True
        if number.comparator == ">" and v > number.value:
            return True
        if number.comparator == ">=" and v >= number.value:
            return True
        if number.comparator:
            continue
        rounding = 0.5 * 10 ** (-number.decimals) + 1e-9
        if "e" in number.raw.lower():
            rounding = abs(number.value) * REL_TOL
        if abs(v - number.value) <= rounding or abs(v - number.value) <= REL_TOL * abs(v):
            return True
    return False


# ------------------------------------------------------------------------------ claim checks


def passage_ids_in(evidence: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Every `passage_id` that appears in any evidence data (docs.search / docs.get_passage)."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            pid = node.get("passage_id")
            if isinstance(pid, str):
                found.add(pid)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for envelope in evidence.values():
        walk(envelope.get("data"))
    return found


@dataclass
class ClaimResult:
    claim: Claim
    notes: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return not self.notes


def check_number(ref: NumberRef, evidence: Mapping[str, Mapping[str, Any]]) -> str | None:
    """None when the reference checks out, else a short note."""
    envelope = evidence.get(ref.evidence_id)
    label = f"number {ref.value:g} ({ref.field} in {ref.evidence_id})"
    if envelope is None:
        return f"{label}: unknown evidence_id"
    if "error" in envelope:
        return f"{label}: evidence is a failed tool call"
    try:
        actual = resolve_path(envelope.get("data"), ref.field)
    except PathError as exc:
        return f"{label}: field not found ({exc})"
    if isinstance(actual, bool) or not isinstance(actual, int | float):
        return f"{label}: field is not numeric"
    if not math.isfinite(float(actual)):
        return f"{label}: field is not finite"
    field_unit = infer_unit(ref.field)
    if ref.unit != field_unit:
        return f"{label}: unit {ref.unit} does not match field unit {field_unit}"
    if not values_match(field_unit, ref.value, float(actual)):
        return f"{label}: evidence value is {actual:g}"
    return None


def check_claim(
    claim: Claim, evidence: Mapping[str, Mapping[str, Any]], passages: set[str]
) -> ClaimResult:
    notes: list[str] = []
    for ref in claim.numbers:
        note = check_number(ref, evidence)
        if note:
            notes.append(note)
    for number in extract_text_numbers(claim.text):
        if not text_number_backed(number, claim.numbers):
            notes.append(f"number '{number.raw}' in the text is not backed by a NumberRef")
    cited = list(dict.fromkeys([*claim.evidence_ids, *(r.evidence_id for r in claim.numbers)]))
    for evidence_id in claim.evidence_ids:
        if evidence_id not in evidence:
            notes.append(f"cites unknown evidence_id {evidence_id}")
    for passage_id in claim.passage_ids:
        if passage_id not in passages:
            notes.append(f"cites unknown passage_id {passage_id}")
    if not cited and not claim.passage_ids:
        notes.append("cites no evidence or passage")
    checked = claim.model_copy(
        update={"evidence_ids": cited, "status": "unsupported" if notes else "supported"}
    )
    return ClaimResult(checked, notes)


@dataclass
class DraftCheck:
    draft: DraftOutput  # every claim's status set
    results: list[ClaimResult]

    @property
    def supported(self) -> int:
        return sum(1 for r in self.results if r.supported)

    @property
    def unsupported(self) -> list[ClaimResult]:
        return [r for r in self.results if not r.supported]

    def notes(self) -> list[str]:
        return [f"{r.claim.text[:80]!r}: {'; '.join(r.notes)}" for r in self.unsupported]


def check_draft(draft: DraftOutput, evidence: Mapping[str, Mapping[str, Any]]) -> DraftCheck:
    passages = passage_ids_in(evidence)
    results: list[ClaimResult] = []

    def run(claims: list[Claim]) -> list[Claim]:
        out = []
        for claim in claims:
            result = check_claim(claim, evidence, passages)
            results.append(result)
            out.append(result.claim)
        return out

    checked = draft.model_copy(
        update={
            "summary": run(draft.summary),
            "findings": run(draft.findings),
            "hypotheses": [
                h.model_copy(update={"support": run(h.support)}) for h in draft.hypotheses
            ],
        }
    )
    return DraftCheck(checked, results)
