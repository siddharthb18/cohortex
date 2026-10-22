"""Backblaze column validation (FR-ING-3) and schema versions (implementation-notes §3).

Known non-SMART columns are fixed by the implementation notes; every other column must match
`smart_<id>_(normalized|raw)`. Anything else fails the run and the error names the column.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

KNOWN_NON_SMART: tuple[str, ...] = (
    "date",
    "serial_number",
    "model",
    "capacity_bytes",
    "failure",
    "datacenter",
    "cluster_id",
    "vault_id",
    "pod_id",
    "pod_slot_num",
    "is_legacy_format",
)
REQUIRED: tuple[str, ...] = ("date", "serial_number", "model", "capacity_bytes", "failure")
SMART_COLUMN = re.compile(r"^smart_(\d+)_(normalized|raw)$")

# DuckDB types used when reading CSVs. Columns whose format is not yet verified against the
# official schema file (open question 2) are read as text so no value is lost.
NON_SMART_TYPES: dict[str, str] = {
    "date": "DATE",
    "serial_number": "VARCHAR",
    "model": "VARCHAR",
    "capacity_bytes": "BIGINT",
    "failure": "INTEGER",
    "datacenter": "VARCHAR",
    "cluster_id": "VARCHAR",
    "vault_id": "VARCHAR",
    "pod_id": "VARCHAR",
    "pod_slot_num": "VARCHAR",
    "is_legacy_format": "VARCHAR",
}
SMART_TYPE = "DOUBLE"


class SchemaError(ValueError):
    """A day file's header does not match the expected schema."""

    def __init__(self, message: str, columns: Sequence[str]) -> None:
        super().__init__(message)
        self.columns = list(columns)


class UnknownColumnError(SchemaError):
    pass


class MissingColumnError(SchemaError):
    pass


def validate_backblaze_columns(columns: Sequence[str], *, where: str = "") -> list[str]:
    """Validate a header; return the lower-cased column names."""
    lowered = [c.strip().lower() for c in columns]
    suffix = f" in {where}" if where else ""
    dupes = sorted({c for c in lowered if lowered.count(c) > 1})
    if dupes:
        raise SchemaError(f"duplicate column(s){suffix}: {', '.join(dupes)}", dupes)
    unknown = [c for c in lowered if c not in KNOWN_NON_SMART and not SMART_COLUMN.match(c)]
    if unknown:
        raise UnknownColumnError(
            f"unknown non-SMART column(s){suffix}: {', '.join(unknown)}", unknown
        )
    missing = [c for c in REQUIRED if c not in lowered]
    if missing:
        raise MissingColumnError(
            f"missing required column(s){suffix}: {', '.join(missing)}", missing
        )
    return lowered


def column_type(lower_name: str) -> str:
    return NON_SMART_TYPES.get(lower_name, SMART_TYPE)


def schema_version(header_line: str) -> str:
    """First 12 hex chars of SHA-256 of the lower-cased header line (without line ending)."""
    line = header_line.rstrip("\r\n").lower()
    return hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]
