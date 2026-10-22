"""Reporter (FR-AGT-9): assemble the `Report` JSON in code and render it as Markdown.

The reporter makes no LLM call. Summary and findings hold supported claims only; every claim
that failed the checker is listed once under `unverified` (FR-AGT-7).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from cohortex_agent.caveats import triggered_caveats
from cohortex_agent.checker import DraftCheck
from cohortex_agent.schemas import Claim, Hypothesis, NumberRef, Report, Scope

MAX_MODEL_LIMITATIONS = 5


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def assemble_report(
    *,
    question: str,
    scope: Scope,
    mode: str,
    model_id: str,
    prompt_hashes: dict[str, str],
    checked: DraftCheck | None,
    evidence: Mapping[str, Mapping[str, Any]],
    extra_limitations: list[str] | None = None,
) -> Report:
    summary: list[Claim] = []
    findings: list[Claim] = []
    hypotheses: list[Hypothesis] = []
    unverified: list[Claim] = []
    actions: list[str] = []
    model_limitations: list[str] = []
    if checked is not None:
        draft = checked.draft
        unverified = [r.claim for r in checked.results if not r.supported]
        findings = [c for c in draft.findings if c.status == "supported"]
        summary = [c for c in draft.summary if c.status == "supported"][:5]
        if not summary:
            summary = findings[:3]
        for hypothesis in draft.hypotheses:
            support = [c for c in hypothesis.support if c.status == "supported"]
            hypotheses.append(hypothesis.model_copy(update={"support": support}))
        actions = [a.strip()[:300] for a in draft.recommended_actions if a.strip()][:5]
        model_limitations = [x[:300] for x in draft.limitations][:MAX_MODEL_LIMITATIONS]
    seen_unverified: set[str] = set()
    unique_unverified = []
    for claim in unverified:
        if claim.text not in seen_unverified:
            seen_unverified.add(claim.text)
            unique_unverified.append(claim)
    reported = [*summary, *findings, *(c for h in hypotheses for c in h.support)]
    limitations = _dedupe(
        [
            *(extra_limitations or []),
            *triggered_caveats(reported, evidence, scope),
            *model_limitations,
        ]
    )
    return Report(
        question=question,
        scope=scope,
        summary=summary,
        findings=findings,
        hypotheses=hypotheses[:4],
        recommended_actions=actions,
        limitations=limitations,
        unverified=unique_unverified,
        mode=mode,  # type: ignore[arg-type]
        model_id=model_id,
        prompt_hashes=prompt_hashes,
    )


# ------------------------------------------------------------------------------ Markdown

_LITERAL = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?!\w)"
)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _matches(literal: str, ref: NumberRef) -> bool:
    value = float(literal.replace(",", ""))
    mantissa = re.split(r"[eE]", literal)[0]
    decimals = len(mantissa.split(".")[1]) if "." in mantissa else 0
    return abs(value - ref.value) <= 0.5 * 10 ** (-decimals) + 1e-9 or abs(
        value - ref.value
    ) <= 0.005 * abs(ref.value)


def link_numbers(claim: Claim) -> str:
    """Claim text with each cited number written as `[value](evidence:ev_...)`."""
    text = claim.text
    spans = [(m.start(), m.end(), m.group(0)) for m in _LITERAL.finditer(text)]
    used: set[int] = set()
    replacements: list[tuple[int, int, str]] = []
    trailing: list[str] = []
    for ref in claim.numbers:
        for index, (start, end, literal) in enumerate(spans):
            if index not in used and _matches(literal, ref):
                used.add(index)
                replacements.append((start, end, f"[{literal}](evidence:{ref.evidence_id})"))
                break
        else:
            trailing.append(f"[{ref.value:g}](evidence:{ref.evidence_id})")
    pieces: list[str] = []
    cursor = 0
    for start, end, link in sorted(replacements):
        pieces.append(_escape(text[cursor:start]))
        pieces.append(link)
        cursor = end
    pieces.append(_escape(text[cursor:]))
    rendered = "".join(pieces)
    if trailing:
        rendered += " (" + ", ".join(trailing) + ")"
    return rendered


def _passage_links(claim: Claim, evidence: Mapping[str, Mapping[str, Any]]) -> str:
    if not claim.passage_ids:
        return ""
    urls: dict[str, str] = {}
    for envelope in evidence.values():
        data = envelope.get("data")
        items = data.get("items", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and "passage_id" in item and "url" in item:
                urls[str(item["passage_id"])] = str(item["url"])
    links = [f"[{pid}]({urls[pid]})" if pid in urls else f"`{pid}`" for pid in claim.passage_ids]
    return " — sources: " + ", ".join(links)


def _claim_line(claim: Claim, evidence: Mapping[str, Mapping[str, Any]]) -> str:
    cites = ""
    uncited = [e for e in claim.evidence_ids if e not in {n.evidence_id for n in claim.numbers}]
    if uncited:
        cites = " " + " ".join(f"[{e}](evidence:{e})" for e in uncited)
    return f"- {link_numbers(claim)}{cites}{_passage_links(claim, evidence)}"


def render_markdown(
    report: Report,
    *,
    status: str = "completed",
    evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    evidence = evidence or {}
    lines = ["# Investigation report", "", f"**Question:** {_escape(report.question)}", ""]
    scope = report.scope
    scope_bits = [
        f"source {scope.source}" if scope.source else "",
        f"models {', '.join(scope.models)}" if scope.models else "",
        f"from {scope.date_from}" if scope.date_from else "",
        f"to {scope.date_to}" if scope.date_to else "",
    ]
    lines.append(
        f"**Scope:** {'; '.join(b for b in scope_bits if b) or 'not specified'} · "
        f"**Mode:** {report.mode} · **Model:** `{report.model_id}` · **Status:** {status}"
    )
    lines.append("")

    def section(title: str, body: list[str], empty: str) -> None:
        lines.extend([f"## {title}", ""])
        lines.extend(body or [f"_{empty}_"])
        lines.append("")

    section("Summary", [_claim_line(c, evidence) for c in report.summary], "No verified summary.")
    section(
        "Findings", [_claim_line(c, evidence) for c in report.findings], "No verified findings."
    )
    hyp_lines: list[str] = []
    for index, hypothesis in enumerate(report.hypotheses, start=1):
        hyp_lines.append(
            f"{index}. **{_escape(hypothesis.statement)}** (confidence: {hypothesis.confidence})"
        )
        hyp_lines.extend(f"   {_claim_line(c, evidence)}" for c in hypothesis.support)
        hyp_lines.append(f"   - _How to confirm:_ {_escape(hypothesis.how_to_confirm)}")
    section("Hypotheses", hyp_lines, "None.")
    section(
        "Recommended actions",
        [f"- {_escape(a)}" for a in report.recommended_actions],
        "None.",
    )
    section("Limitations", [f"- {_escape(x)}" for x in report.limitations], "None noted.")
    section(
        "Unverified",
        [f"{_claim_line(c, evidence)} _(failed the evidence check)_" for c in report.unverified],
        "Every claim passed the evidence check.",
    )
    return "\n".join(lines).rstrip() + "\n"
