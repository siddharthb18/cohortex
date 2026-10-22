"""WP-02: V1__init.sql is the contracts §2 DDL verbatim and applies cleanly."""

from __future__ import annotations

import re

import psycopg
from cohortex_ingest.migrate import apply_v1_if_needed, v1_path, v1_sql
from cohortex_ingest.paths import find_repo_file

EXPECTED_TABLES = {
    "ingest_run",
    "drive_model",
    "drive",
    "cohort_daily",
    "smart_daily",
    "alert",
    "investigation",
    "investigation_step",
    "evidence",
    "claim",
    "document",
    "chunk",
    "eval_run",
    "eval_case_result",
    "human_label",
    "llm_spend",
}


def test_v1_is_contracts_ddl_verbatim() -> None:
    contracts = find_repo_file("docs/specs/contracts.md").read_text(encoding="utf-8")
    section = contracts.split("## 2. Serving database DDL", 1)[1]
    match = re.search(r"```sql\n(.*?)```", section, re.DOTALL)
    assert match is not None
    assert v1_path().read_text(encoding="utf-8") == match.group(1)


def test_only_placeholder_is_embedding_dim() -> None:
    text = v1_path().read_text(encoding="utf-8")
    assert re.findall(r"\$\{(\w+)\}", text) == ["embedding_dim"]
    assert "vector(384)" in v1_sql(384)
    assert "${" not in v1_sql(384)


def test_v1_creates_all_tables(pg: psycopg.Connection) -> None:
    rows = pg.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename NOT LIKE "
        "'smart_daily_y%'"
    ).fetchall()
    assert {r[0] for r in rows} >= EXPECTED_TABLES
    dim = pg.execute(
        "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunk'::regclass "
        "AND attname = 'embedding'"
    ).fetchone()
    assert dim == (384,)


def test_apply_is_skipped_when_schema_present(pg: psycopg.Connection) -> None:
    assert apply_v1_if_needed(pg, embedding_dim=384) is False


def test_apply_is_skipped_when_flyway_owns_schema(pg_url: str) -> None:
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE flyway_schema_history (installed_rank int)")
        try:
            assert apply_v1_if_needed(conn, embedding_dim=384) is False
        finally:
            conn.execute("DROP TABLE flyway_schema_history")
