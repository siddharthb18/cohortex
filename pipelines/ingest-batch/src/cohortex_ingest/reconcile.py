"""Raw vs serving reconciliation (FR-ING-5, implementation-notes §3).

Per model, drive-days and failures from `drive_day` (raw layer) must equal the sums of
`cohort_daily` (serving layer) for the period. The result is stored in
`ingest_run.reconciliation` as `{"ok": bool, "models": [...]}`.
"""

from __future__ import annotations

from datetime import date

import duckdb
import psycopg
from pydantic import BaseModel

from cohortex_ingest.quarters import Quarter


class ModelReconciliation(BaseModel):
    model: str | None
    raw_drive_days: int
    serving_drive_days: int
    raw_failures: int
    serving_failures: int

    @property
    def ok(self) -> bool:
        return (
            self.raw_drive_days == self.serving_drive_days
            and self.raw_failures == self.serving_failures
        )


class Reconciliation(BaseModel):
    ok: bool
    models: list[ModelReconciliation]

    def mismatches(self) -> list[ModelReconciliation]:
        return [m for m in self.models if not m.ok]


class ReconciliationError(RuntimeError):
    def __init__(self, result: Reconciliation) -> None:
        names = ", ".join(str(m.model) for m in result.mismatches()) or "(no rows)"
        super().__init__(f"reconciliation failed for: {names}")
        self.result = result


def reconcile_period(
    pg: psycopg.Connection,
    duck: duckdb.DuckDBPyConnection,
    source: str,
    start: date,
    end: date,
) -> Reconciliation:
    raw_rows = duck.execute(
        "SELECT model, count(*), coalesce(sum(failure), 0) FROM drive_day "
        "WHERE source = ? AND day BETWEEN ? AND ? GROUP BY model",
        [source, start, end],
    ).fetchall()
    serving_rows = pg.execute(
        "SELECT m.model, sum(c.drive_count), sum(c.failures) FROM cohort_daily c "
        "JOIN drive_model m ON m.id = c.model_id "
        "WHERE m.source = %s AND c.day BETWEEN %s AND %s GROUP BY m.model",
        (source, start, end),
    ).fetchall()
    raw = {r[0]: (int(r[1]), int(r[2])) for r in raw_rows}
    serving = {r[0]: (int(r[1]), int(r[2])) for r in serving_rows}
    models = [
        ModelReconciliation(
            model=name,
            raw_drive_days=raw.get(name, (0, 0))[0],
            serving_drive_days=serving.get(name, (0, 0))[0],
            raw_failures=raw.get(name, (0, 0))[1],
            serving_failures=serving.get(name, (0, 0))[1],
        )
        for name in sorted(raw.keys() | serving.keys(), key=lambda m: (m is None, m or ""))
    ]
    ok = bool(models) and all(m.ok for m in models)
    return Reconciliation(ok=ok, models=models)


def reconcile_quarter(
    pg: psycopg.Connection, duck: duckdb.DuckDBPyConnection, source: str, quarter: Quarter
) -> Reconciliation:
    return reconcile_period(pg, duck, source, quarter.start, quarter.end)
