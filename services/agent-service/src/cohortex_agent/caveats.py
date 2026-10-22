"""Dataset caveats (contracts §6) that code adds to `limitations` when triggered (FR-AGT-9).

Triggers are computed from evidence, not from the model's text, so a caveat cannot be forgotten:

- Small cohort: a cohort record that a reported claim relies on (the object holding a cited
  field, or every record of evidence cited without numbers) has `failures` < 3 or a drive count
  (`drive_count`, `drives`, `n_drives`) < 60.
- Backblaze / Alibaba: any evidence or the scope uses that source.
- SMART statements: any SMART evidence (`fleet.smart_trend`, `fleet.failed_drives`) or a reported
  claim that mentions SMART.
- SMART sample: any `fleet.smart_trend` evidence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from cohortex_agent.checker import PathError, resolve_path
from cohortex_agent.schemas import Claim, Scope

SMALL_COHORT = (
    "Small cohort: fewer than 60 drives or fewer than 3 failures make AFR unstable; "
    "read the 95% interval, not the point estimate."
)
BACKBLAZE_FIRST_DAY = "Backblaze data: drives that fail on their first day are not captured."
SMART_NO_SIGNAL = "SMART-based statements: many failures show no prior SMART signal."
SMART_SAMPLE = "SMART trends come from a 1% sample plus failed drives, not the full cohort."
ALIBABA_PERIOD = "Alibaba data covers 2018\u20132019 only."

_DRIVE_COUNT_FIELDS = ("drive_count", "drives", "n_drives")
_SMART_TOOLS = ("fleet.smart_trend", "fleet.failed_drives")


def _parent_path(field: str) -> str:
    """`items[2].afr_pct` -> `items[2]`; `afr_pct` -> `` (the data root)."""
    stripped = re.sub(r"\.?[A-Za-z_][A-Za-z0-9_]*$", "", field.strip())
    return stripped


def _records(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _records(value)
    elif isinstance(node, list):
        for value in node:
            yield from _records(value)


def _is_small(record: Mapping[str, Any]) -> bool:
    failures = record.get("failures")
    if isinstance(failures, int | float) and not isinstance(failures, bool) and failures < 3:
        return True
    for name in _DRIVE_COUNT_FIELDS:
        value = record.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool) and value < 60:
            return True
    return False


def _sources(envelope: Mapping[str, Any]) -> set[str]:
    found: set[str] = set()
    args = envelope.get("args")
    if isinstance(args, dict) and isinstance(args.get("source"), str):
        found.add(args["source"])
    data = envelope.get("data")
    if isinstance(data, dict) and isinstance(data.get("source"), str):
        found.add(data["source"])
    return found


def triggered_caveats(
    claims: Iterable[Claim], evidence: Mapping[str, Mapping[str, Any]], scope: Scope
) -> list[str]:
    claims = list(claims)
    caveats: list[str] = []

    small = False
    for claim in claims:
        number_evidence = {ref.evidence_id for ref in claim.numbers}
        for ref in claim.numbers:
            envelope = evidence.get(ref.evidence_id)
            if envelope is None:
                continue
            parent = _parent_path(ref.field)
            try:
                record = resolve_path(envelope.get("data"), parent) if parent else envelope["data"]
            except (PathError, KeyError):
                continue
            if isinstance(record, dict) and _is_small(record):
                small = True
        for evidence_id in claim.evidence_ids:
            envelope = evidence.get(evidence_id)
            if envelope is None or evidence_id in number_evidence:
                continue
            if any(_is_small(r) for r in _records(envelope.get("data"))):
                small = True
    if small:
        caveats.append(SMALL_COHORT)

    sources: set[str] = {scope.source} if scope.source else set()
    tools: set[str] = set()
    for envelope in evidence.values():
        if "error" in envelope:
            continue
        sources |= _sources(envelope)
        tools.add(str(envelope.get("tool", "")))
    if "backblaze" in sources:
        caveats.append(BACKBLAZE_FIRST_DAY)
    mentions_smart = any(re.search(r"\bSMART\b", c.text, re.IGNORECASE) for c in claims)
    if mentions_smart or tools & set(_SMART_TOOLS):
        caveats.append(SMART_NO_SIGNAL)
    if "fleet.smart_trend" in tools:
        caveats.append(SMART_SAMPLE)
    if "alibaba" in sources:
        caveats.append(ALIBABA_PERIOD)
    return caveats
