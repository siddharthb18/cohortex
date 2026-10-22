"""DuckDB connections with bounded memory, so a full Backblaze quarter fits on a small machine.

`COHORTEX_DUCKDB_MEMORY_LIMIT` (default ``2GB``) and `COHORTEX_DUCKDB_THREADS` (default ``2``) bound
each connection; larger-than-memory work spills to `COHORTEX_DUCKDB_TEMP_DIR` (default: DuckDB's).
"""

from __future__ import annotations

import os

import duckdb


def duck_connect(database: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with the configured memory and thread limits."""
    con = duckdb.connect(database)
    con.execute(f"SET memory_limit = '{_setting('COHORTEX_DUCKDB_MEMORY_LIMIT', '2GB')}'")
    con.execute(f"SET threads = {int(_setting('COHORTEX_DUCKDB_THREADS', '2'))}")
    con.execute("SET preserve_insertion_order = false")
    temp_dir = os.environ.get("COHORTEX_DUCKDB_TEMP_DIR")
    if temp_dir:
        con.execute(f"SET temp_directory = '{temp_dir}'")
    return con


def _setting(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip() or default
    if not all(ch.isalnum() or ch in "._/-" for ch in value):
        raise ValueError(f"{name} has an invalid value")
    return value
