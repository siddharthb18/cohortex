"""``--store``: eval_run / eval_case_result rows in a throwaway Postgres DB."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest
from cohortex_evals.gate import GateResult
from cohortex_evals.records import CaseResult
from cohortex_evals.reporting import RunReport
from cohortex_evals.settings import RepoPaths
from cohortex_evals.store import store_run
from psycopg import sql
from psycopg.conninfo import make_conninfo

ADMIN_URL = os.environ.get(
    "COHORTEX_TEST_DATABASE_URL", "postgresql://cohortex@localhost:5432/cohortex"
)
EMBEDDING_DIM = os.environ.get("EMBEDDING_DIM", "384")


def _ddl(paths: RepoPaths) -> str:
    real = paths.root / "db/migrations/V1__init.sql"
    source = real if real.is_file() else paths.root / "evals/harness/tests/sql/V1__init.sql"
    return source.read_text("utf-8").replace("${embedding_dim}", EMBEDDING_DIM)


@pytest.fixture(scope="module")
def database_url(paths: RepoPaths) -> Iterator[str]:
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable at {ADMIN_URL}: {exc}")
    name = f"cohortex_test_evals_{uuid.uuid4().hex[:8]}"
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url) as conn, conn.transaction():
            conn.execute(_ddl(paths).encode())
        yield url
    finally:
        admin.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )
        admin.close()


def _report(existing_inv: str, missing_inv: str) -> RunReport:
    now = datetime.now(UTC)
    cases = [
        CaseResult(
            case_id="lookup-0001",
            category="lookup",
            reviewed=True,
            must_refuse=False,
            investigation_id=existing_inv,
            status="completed",
            passed=True,
        ),
        CaseResult(
            case_id="lookup-0002",
            category="lookup",
            reviewed=True,
            must_refuse=False,
            investigation_id=missing_inv,
            status="completed",
            passed=False,
        ),
        CaseResult(
            case_id="lookup-0003",
            category="lookup",
            reviewed=True,
            must_refuse=False,
            investigation_id=None,
            status="error",
            passed=False,
        ),
    ]
    gate = GateResult(
        status="failed", level="gate", golden_version="v1", reviewed_cases=3, reasons=["M1"]
    )
    return RunReport(
        run_id=str(uuid.uuid4()),
        started_at=now,
        finished_at=now,
        git_sha="abc",
        golden_version="v1",
        mode="single",
        recorded=True,
        llm_model="gpt-oss-20b",
        agent_api_url="http://agent",
        case_files=["evals/golden/v1/cases.jsonl"],
        metrics={},
        gate=gate,
        cases=cases,
        runs=[],
    )


def test_store_run_inserts_rows_and_respects_investigation_fk(database_url: str) -> None:
    existing, missing = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO investigation (id, question, mode, status, llm_model, prompt_hashes, "
            "started_at) "
            "VALUES (%s, 'q', 'single', 'completed', 'gpt-oss-20b', '{}', now())",
            (existing,),
        )
    report = _report(existing, missing)
    assert store_run(database_url, report) == 4
    with psycopg.connect(database_url) as conn:
        run = conn.execute(
            "SELECT golden_version, mode, recorded, passed, metrics->>'gate_status' "
            "FROM eval_run WHERE id = %s",
            (report.run_id,),
        ).fetchone()
        assert run == ("v1", "single", True, False, "failed")
        rows = conn.execute(
            "SELECT case_id, investigation_id::text, passed, scores->>'status' "
            "FROM eval_case_result WHERE eval_run_id = %s ORDER BY case_id",
            (report.run_id,),
        ).fetchall()
        assert rows == [
            ("lookup-0001", existing, True, "completed"),
            ("lookup-0002", None, False, "completed"),  # no investigation row: FK kept null
            ("lookup-0003", None, False, "error"),
        ]
        linked = conn.execute(
            "SELECT eval_run_id::text FROM investigation WHERE id = %s", (existing,)
        ).fetchone()
        assert linked == (report.run_id,)
