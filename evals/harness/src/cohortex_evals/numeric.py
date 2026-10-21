"""Numeric helpers: JSON-path lookup into evidence and the FR-AGT-6 tolerance rule."""

from __future__ import annotations

import math
import re
from typing import Any

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

# contracts §6 numeric check rule: counts must match exactly; percentages within 0.5% relative or
# 0.01 absolute. The rule names only those two kinds, so every non-count unit uses the
# percentage tolerance here (documented in evals/harness/README.md).
EXACT_UNITS = frozenset({"count", "drive_days", "days"})
REL_TOL = 0.005
ABS_TOL = 0.01


class PathError(LookupError):
    """A NumberRef field path does not resolve in the evidence."""


def resolve_path(data: Any, path: str) -> Any:
    """Read ``series[0].afr_pct``-style paths. A leading ``$`` or ``$.`` is ignored."""
    clean = path.strip()
    if clean.startswith("$"):
        clean = clean[1:].lstrip(".")
    if not clean:
        raise PathError("empty path")
    pos = 0
    current = data
    for match in _TOKEN_RE.finditer(clean):
        if clean[pos : match.start()].strip(".") != "":
            raise PathError(f"malformed path {path!r}")
        pos = match.end()
        key, index = match.group(1), match.group(2)
        if index is not None:
            if not isinstance(current, list) or int(index) >= len(current):
                raise PathError(f"{path!r}: index {index} out of range")
            current = current[int(index)]
        else:
            if not isinstance(current, dict) or key not in current:
                raise PathError(f"{path!r}: no key {key!r}")
            current = current[key]
    if clean[pos:].strip(".") != "":
        raise PathError(f"malformed path {path!r}")
    return current


def evidence_value(evidence: dict[str, Any], path: str) -> Any:
    """Resolve a NumberRef ``field`` against fetched evidence.

    ``evidence`` is the ``GET .../evidence/{id}`` body: ``{evidence_id, tool, args, result}`` where
    ``result`` is the tool envelope whose ``data`` the field path is relative to. Falls back to the
    envelope and then the whole body so ``data.x`` and ``x`` both work.
    """
    envelope = evidence.get("result")
    roots: list[Any] = []
    if isinstance(envelope, dict):
        roots.append(envelope.get("data"))
        roots.append(envelope)
    roots.append(evidence)
    last: PathError | None = None
    for root in roots:
        if root is None:
            continue
        try:
            return resolve_path(root, path)
        except PathError as exc:
            last = exc
    raise last or PathError(f"{path!r}: evidence has no data")


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    return None


def values_match(claimed: float, actual: float, unit: str) -> bool:
    """FR-AGT-6 rule used by the independent recheck (M4)."""
    if unit in EXACT_UNITS:
        return claimed == actual
    diff = abs(claimed - actual)
    return diff <= ABS_TOL or diff <= REL_TOL * abs(actual)


def within_tolerance(
    value: float, truth: float, abs_tol: float | None, rel_tol: float | None
) -> bool:
    """Golden-case tolerance: pass when within ``abs_tol`` or within ``rel_tol`` of truth."""
    diff = abs(value - truth)
    if abs_tol is not None and diff <= abs_tol + 1e-12:
        return True
    return rel_tol is not None and diff <= rel_tol * abs(truth) + 1e-12
