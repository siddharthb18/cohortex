"""DuckDB over the Parquet raw layer (contracts §1, ``contracts/rawlayer/views.sql``).

ADR-004: eval truth is computed only here, never from Postgres. This module must not import a
Postgres driver.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class SourceView:
    """A view that reads Parquet files, and the empty stand-in used when there are none."""

    pattern: str
    empty_select: str


# Empty stand-ins keep the non-SMART columns that downstream views (and truth SQL) use.
SOURCE_VIEWS: dict[str, SourceView] = {
    "raw_backblaze_day": SourceView(
        pattern="{raw}/backblaze/*/*/*.parquet",
        empty_select=(
            "SELECT CAST(NULL AS DATE) AS date, CAST(NULL AS VARCHAR) AS serial_number, "
            "CAST(NULL AS VARCHAR) AS model, CAST(NULL AS BIGINT) AS capacity_bytes, "
            "CAST(NULL AS INTEGER) AS failure, CAST(NULL AS VARCHAR) AS datacenter, "
            "CAST(NULL AS VARCHAR) AS cluster_id, CAST(NULL AS VARCHAR) AS vault_id, "
            "CAST(NULL AS VARCHAR) AS pod_id, CAST(NULL AS VARCHAR) AS pod_slot_num, "
            "CAST(NULL AS VARCHAR) AS is_legacy_format, CAST(NULL AS VARCHAR) AS schema_version, "
            "CAST(NULL AS BIGINT) AS year, CAST(NULL AS VARCHAR) AS quarter WHERE false"
        ),
    ),
    "raw_alibaba_day": SourceView(
        pattern="{raw}/alibaba/smart/*/*/*.parquet",
        empty_select=(
            "SELECT CAST(NULL AS VARCHAR) AS disk_id, CAST(NULL AS VARCHAR) AS ds, "
            "CAST(NULL AS VARCHAR) AS model, CAST(NULL AS DATE) AS source_file_date, "
            "CAST(NULL AS BIGINT) AS year, CAST(NULL AS BIGINT) AS month WHERE false"
        ),
    ),
    "raw_alibaba_failure": SourceView(
        pattern="{raw}/alibaba/failure_label.parquet",
        empty_select=(
            "SELECT CAST(NULL AS VARCHAR) AS model, CAST(NULL AS VARCHAR) AS disk_id, "
            "CAST(NULL AS TIMESTAMP) AS failure_time WHERE false"
        ),
    ),
}

_VIEW_RE = re.compile(r"^\s*CREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+)", re.IGNORECASE)


def _strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def split_statements(sql: str) -> list[str]:
    """Split ``views.sql`` into statements (it is plain SQL separated by semicolons)."""
    return [s.strip() for s in _strip_comments(sql).split(";") if s.strip()]


def normalize_raw_uri(raw_uri: str) -> str:
    uri = raw_uri.rstrip("/")
    return uri or "/"


def _sql_literal_safe(value: str) -> str:
    return value.replace("'", "''")


def _glob(con: duckdb.DuckDBPyConnection, pattern: str) -> list[str]:
    rows = con.execute("SELECT file FROM glob(?) ORDER BY file", [pattern]).fetchall()
    return [str(r[0]) for r in rows]


def open_raw_layer(
    raw_uri: str,
    views_sql: Path,
    con: duckdb.DuckDBPyConnection | None = None,
) -> duckdb.DuckDBPyConnection:
    """Create the raw-layer views on an in-memory DuckDB connection.

    Sources without files get empty views of the same core columns, so ``drive_day`` always exists.
    """
    con = con or duckdb.connect(":memory:")
    raw = normalize_raw_uri(raw_uri)
    for stmt in split_statements(views_sql.read_text(encoding="utf-8")):
        match = _VIEW_RE.match(stmt)
        name = match.group(1).lower() if match else None
        if name in SOURCE_VIEWS:
            source = SOURCE_VIEWS[name]
            if not _glob(con, source.pattern.format(raw=raw)):
                con.execute(f"CREATE OR REPLACE VIEW {name} AS {source.empty_select}")
                continue
        con.execute(stmt.replace("{raw}", _sql_literal_safe(raw)))
    return con


def raw_files(con: duckdb.DuckDBPyConnection, raw_uri: str) -> list[tuple[str, int]]:
    """All raw-layer files read by the views, as (path relative to the raw root, size in bytes)."""
    raw = normalize_raw_uri(raw_uri)
    files: list[str] = []
    for source in SOURCE_VIEWS.values():
        files.extend(_glob(con, source.pattern.format(raw=raw)))
    if not files:
        return []
    rows = con.execute(
        "SELECT filename, size FROM read_blob(?) ORDER BY filename", [sorted(files)]
    ).fetchall()
    prefix = raw.rstrip("/") + "/"
    out: list[tuple[str, int]] = []
    for filename, size in rows:
        name = str(filename)
        out.append((name[len(prefix) :] if name.startswith(prefix) else name, int(size)))
    return sorted(out)


def snapshot_id(con: duckdb.DuckDBPyConnection, raw_uri: str) -> str:
    """Stable ID of the raw layer: hash of the sorted file list with sizes."""
    digest = hashlib.sha256()
    for name, size in raw_files(con, raw_uri):
        digest.update(f"{name}\t{size}\n".encode())
    return "snap_" + digest.hexdigest()[:16]
