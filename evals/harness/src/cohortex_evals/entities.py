"""Entity matching for the ``entities`` and ``diagnostic_set`` graders.

Model names are compared normalized: upper-case with spaces and dashes removed, so
``WDC WUH721816ALE6L4`` matches ``wdc wuh721816ale6l4`` and ``WUH721816-ALE6L4``. A vendor prefix
(``TOSHIBA``, ``WDC``, ``HGST``, ...) is optional because reports often drop it. Periods match in
either order (``Q2 2026`` == ``2026Q2`` == ``2026 Q2``).
"""

from __future__ import annotations

import re
from functools import lru_cache

VENDOR_PREFIXES = frozenset({"TOSHIBA", "WDC", "WD", "HGST", "SEAGATE", "HITACHI"})
_SEP = r"[\s\-]*"
_QUARTER_RE = re.compile(r"^\s*(?:(Q[1-4])[\s\-]*(\d{4})|(\d{4})[\s\-]*(Q[1-4]))\s*$", re.I)
_HALF_RE = re.compile(r"^\s*(?:(H[12])[\s\-]*(\d{4})|(\d{4})[\s\-]*(H[12]))\s*$", re.I)


def normalize_model(name: str) -> str:
    return re.sub(r"[\s\-]+", "", name).upper()


def _spaced(token: str) -> str:
    return _SEP.join(re.escape(ch) for ch in normalize_model(token))


def _bounded(body: str) -> str:
    return rf"(?<![A-Za-z0-9])(?:{body})(?![A-Za-z0-9])"


def _period_pattern(entity: str) -> str | None:
    for regex in (_QUARTER_RE, _HALF_RE):
        m = regex.match(entity)
        if m:
            part = (m.group(1) or m.group(4)).upper()
            year = m.group(2) or m.group(3)
            return f"{part}{_SEP}{year}|{year}{_SEP}{part}"
    return None


@lru_cache(maxsize=1024)
def entity_regex(entity: str) -> re.Pattern[str]:
    period = _period_pattern(entity)
    if period is not None:
        return re.compile(_bounded(period), re.IGNORECASE)
    alternatives = [_spaced(entity)]
    tokens = entity.split()
    if len(tokens) > 1 and tokens[0].upper() in VENDOR_PREFIXES:
        rest = " ".join(tokens[1:])
        if len(normalize_model(rest)) >= 4:
            alternatives.append(_spaced(rest))
    return re.compile(_bounded("|".join(alternatives)), re.IGNORECASE)


def mentions(text: str, entity: str) -> bool:
    return bool(entity.strip()) and entity_regex(entity).search(text) is not None


def named_models(text: str, candidates: list[str]) -> set[str]:
    """Candidate models (normalized) that the text names."""
    return {normalize_model(c) for c in candidates if mentions(text, c)}
