"""DuckDB connection over the raw layer, using the shared views in contracts/rawlayer/views.sql.

`{raw}` is replaced with RAW_DATA_URI. When a view's `read_parquet()` pattern matches no file yet
(for example, no Alibaba data loaded), that view is replaced by an empty view with the same
columns, so `drive_day` always exists.
"""

from __future__ import annotations

import re

import duckdb

from cohortex_ingest.paths import duckdb_raw_uri, find_repo_file

VIEWS_RELATIVE = "contracts/rawlayer/views.sql"
_VIEW_NAME = re.compile(r"CREATE\s+OR\s+REPLACE\s+VIEW\s+(\w+)", re.IGNORECASE)
_PARQUET_PATTERN = re.compile(r"read_parquet\(\s*'([^']+)'")

# Empty stand-ins: the columns the downstream views and truth queries rely on.
EMPTY_VIEWS: dict[str, str] = {
    "raw_backblaze_day": (
        "SELECT CAST(NULL AS DATE) AS date, CAST(NULL AS VARCHAR) AS serial_number, "
        "CAST(NULL AS VARCHAR) AS model, CAST(NULL AS BIGINT) AS capacity_bytes, "
        "CAST(NULL AS INTEGER) AS failure, CAST(NULL AS VARCHAR) AS schema_version, "
        "CAST(NULL AS BIGINT) AS year, CAST(NULL AS VARCHAR) AS quarter WHERE false"
    ),
    "raw_alibaba_day": (
        "SELECT CAST(NULL AS VARCHAR) AS disk_id, CAST(NULL AS VARCHAR) AS ds, "
        "CAST(NULL AS VARCHAR) AS model, CAST(NULL AS DATE) AS source_file_date, "
        "CAST(NULL AS BIGINT) AS year, CAST(NULL AS BIGINT) AS month WHERE false"
    ),
    "raw_alibaba_failure": (
        "SELECT CAST(NULL AS VARCHAR) AS model, CAST(NULL AS VARCHAR) AS disk_id, "
        "CAST(NULL AS TIMESTAMP) AS failure_time WHERE false"
    ),
}


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def view_statements(raw_uri: str) -> list[tuple[str, str]]:
    """`(view_name, sql)` for every statement in views.sql, with `{raw}` substituted."""
    text = find_repo_file(VIEWS_RELATIVE).read_text(encoding="utf-8")
    text = _strip_comments(text).replace("{raw}", duckdb_raw_uri(raw_uri))
    out: list[tuple[str, str]] = []
    for stmt in (s.strip() for s in text.split(";")):
        if not stmt:
            continue
        m = _VIEW_NAME.search(stmt)
        if not m:
            raise ValueError(f"unexpected statement in {VIEWS_RELATIVE}: {stmt[:60]!r}")
        out.append((m.group(1), stmt))
    return out


def _has_files(con: duckdb.DuckDBPyConnection, pattern: str) -> bool:
    row = con.execute("SELECT count(*) FROM glob(?)", [pattern]).fetchone()
    return bool(row and row[0])


def connect(raw_uri: str, database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """A DuckDB connection with the raw-layer views (`drive_day` and friends) defined."""
    con = duckdb.connect(database)
    for name, stmt in view_statements(raw_uri):
        m = _PARQUET_PATTERN.search(stmt)
        if m and not _has_files(con, m.group(1)):
            if name not in EMPTY_VIEWS:
                raise ValueError(f"no empty definition for view {name}")
            con.execute(f"CREATE OR REPLACE VIEW {name} AS {EMPTY_VIEWS[name]}")
        else:
            con.execute(stmt)
    return con
