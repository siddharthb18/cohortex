"""Apply Flyway's V1 from Python (implementation-notes §2).

fleet-api runs Flyway in production. Python code and tests apply the same file, with
`${embedding_dim}` replaced, only when Flyway has not run (no `flyway_schema_history`) and the
schema is not there yet. Python never owns later migrations.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from cohortex_ingest.paths import find_repo_file

V1_RELATIVE = "db/migrations/V1__init.sql"


def v1_path() -> Path:
    return find_repo_file(V1_RELATIVE)


def v1_sql(embedding_dim: int) -> str:
    if embedding_dim <= 0:
        raise ValueError("embedding_dim must be positive")
    return v1_path().read_text(encoding="utf-8").replace("${embedding_dim}", str(embedding_dim))


def _exists(conn: psycopg.Connection, table: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",)).fetchone()
    return bool(row and row[0])


def apply_v1_if_needed(conn: psycopg.Connection, *, embedding_dim: int) -> bool:
    """Apply V1 in one transaction. Returns True when it was applied."""
    if _exists(conn, "flyway_schema_history") or _exists(conn, "ingest_run"):
        return False
    script = v1_sql(embedding_dim)
    with conn.transaction():
        # No parameters, so psycopg sends the multi-statement script as one simple query.
        conn.execute(script.encode())
    return True
