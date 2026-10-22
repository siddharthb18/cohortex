"""FR-ING-5: reconcile drive-days and failures per model between raw and serving layers; fail on
mismatch. Acceptance: corrupting one serving row makes reconciliation fail."""

from __future__ import annotations

from pathlib import Path

import psycopg
from cohortex_ingest.derive_load import load_quarter
from cohortex_ingest.quarters import Quarter
from cohortex_ingest.rawlayer import connect
from cohortex_ingest.reconcile import reconcile_quarter
from cohortex_ingest.synthetic import SyntheticSummary

Q2 = Quarter.parse("2026Q2")


def test_clean_load_reconciles(
    pg: psycopg.Connection, raw_q2_shared: Path, synthetic_q2: tuple[Path, SyntheticSummary]
) -> None:
    _, summary = synthetic_q2
    duck = connect(str(raw_q2_shared))
    load_quarter(pg, duck, "backblaze", Q2)
    result = reconcile_quarter(pg, duck, "backblaze", Q2)
    assert result.ok
    assert [m.model for m in result.models] == sorted(summary.models)
    for m in result.models:
        assert m.model is not None
        assert m.raw_drive_days == m.serving_drive_days == summary.models[m.model].drive_days
        assert m.raw_failures == m.serving_failures == summary.models[m.model].failures
    as_json = result.model_dump(mode="json")
    assert set(as_json) == {"ok", "models"}
    assert set(as_json["models"][0]) == {
        "model",
        "raw_drive_days",
        "serving_drive_days",
        "raw_failures",
        "serving_failures",
    }


def test_corrupting_one_serving_row_fails(pg: psycopg.Connection, raw_q2_shared: Path) -> None:
    duck = connect(str(raw_q2_shared))
    load_quarter(pg, duck, "backblaze", Q2)
    pg.execute(
        "UPDATE cohort_daily SET failures = failures + 1 "
        "WHERE (model_id, day) = (SELECT model_id, day FROM cohort_daily ORDER BY 1, 2 LIMIT 1)"
    )
    result = reconcile_quarter(pg, duck, "backblaze", Q2)
    assert not result.ok
    bad = [m for m in result.models if m.raw_failures != m.serving_failures]
    assert len(bad) == 1
    assert bad[0].serving_failures == bad[0].raw_failures + 1


def test_missing_serving_rows_fail(pg: psycopg.Connection, raw_q2_shared: Path) -> None:
    duck = connect(str(raw_q2_shared))
    load_quarter(pg, duck, "backblaze", Q2)
    pg.execute(
        "DELETE FROM cohort_daily WHERE day = '2026-06-30' "
        "AND model_id = (SELECT min(model_id) FROM cohort_daily)"
    )
    result = reconcile_quarter(pg, duck, "backblaze", Q2)
    assert not result.ok
    assert sum(m.raw_drive_days != m.serving_drive_days for m in result.models) == 1


def test_nothing_loaded_fails(pg: psycopg.Connection, raw_q2_shared: Path) -> None:
    result = reconcile_quarter(pg, connect(str(raw_q2_shared)), "backblaze", Q2)
    assert not result.ok
    assert all(m.serving_drive_days == 0 for m in result.models)
