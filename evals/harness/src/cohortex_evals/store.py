"""Optional storage of a run in Postgres ``eval_run`` / ``eval_case_result`` (contracts §2).

Only results are stored here; truth never comes from Postgres (ADR-004).
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from cohortex_evals.reporting import RunReport


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def run_metrics_json(report: RunReport) -> dict[str, Any]:
    return {
        "gate_status": report.gate.status,
        "reviewed_cases": report.gate.reviewed_cases,
        "gate": {k: v.model_dump(mode="json") for k, v in report.gate.metrics.items()},
        "all": {k: v.model_dump(mode="json") for k, v in report.metrics.items()},
        "reasons": report.gate.reasons,
    }


def store_run(database_url: str, report: RunReport) -> int:
    """Insert one ``eval_run`` and its ``eval_case_result`` rows in a single transaction.

    ``investigation_id`` is stored only when that investigation row exists (FK); matching
    investigations get ``eval_run_id`` set so traces link back to the run. Returns rows written.
    """
    candidate_ids = [c.investigation_id for c in report.cases if _is_uuid(c.investigation_id)]
    with psycopg.connect(database_url) as conn, conn.transaction():
        existing: set[str] = set()
        if candidate_ids:
            rows = conn.execute(
                "SELECT id::text FROM investigation WHERE id = ANY(%s::uuid[])", (candidate_ids,)
            ).fetchall()
            existing = {str(r[0]) for r in rows}
        conn.execute(
            "INSERT INTO eval_run (id, started_at, git_sha, golden_version, mode, llm_model, "
            "recorded, metrics, passed) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                report.run_id,
                report.started_at,
                report.git_sha,
                report.golden_version,
                report.mode,
                report.llm_model,
                report.recorded,
                Jsonb(run_metrics_json(report)),
                report.gate.status != "failed",
            ),
        )
        for case in report.cases:
            inv = case.investigation_id if case.investigation_id in existing else None
            conn.execute(
                "INSERT INTO eval_case_result (eval_run_id, case_id, investigation_id, passed, "
                "scores) VALUES (%s, %s, %s, %s, %s)",
                (
                    report.run_id,
                    case.case_id,
                    inv,
                    case.passed,
                    Jsonb(case.model_dump(mode="json")),
                ),
            )
        if existing:
            conn.execute(
                "UPDATE investigation SET eval_run_id = %s WHERE id = ANY(%s::uuid[])",
                (report.run_id, sorted(existing)),
            )
    return 1 + len(report.cases)
