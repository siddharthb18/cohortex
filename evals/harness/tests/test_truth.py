"""Truth runner over a synthetic raw layer built in the contract layout (ADR-004)."""

from __future__ import annotations

import math
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from cohortex_evals.cases import GoldenCase, load_cases
from cohortex_evals.rawlayer import open_raw_layer, raw_files, snapshot_id, split_statements
from cohortex_evals.settings import RepoPaths
from cohortex_evals.testing import write_backblaze_day
from cohortex_evals.truth import TruthError, compute_truth, explain_truth_sql, run_truth


def _case(sql: str, **overrides: Any) -> GoldenCase:
    data: dict[str, Any] = {
        "id": "lookup-0001",
        "category": "lookup",
        "question": "q",
        "truth_sql": sql,
        "primary_answer": {"field": "afr_pct", "unit": "pct", "abs_tol": 0.01},
        "must_refuse": False,
    }
    data.update(overrides)
    return GoldenCase.model_validate(data)


AFR_A = (
    "SELECT COUNT(*) AS drive_days, SUM(failure) AS failures, "
    "CAST(SUM(failure) AS DOUBLE) * 365 * 100 / COUNT(*) AS afr_pct "
    "FROM drive_day WHERE source = 'backblaze' AND model = 'A' "
    "AND day BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'"
)


def test_views_split_into_statements(paths: RepoPaths) -> None:
    stmts = split_statements(paths.views_sql.read_text("utf-8"))
    assert len(stmts) == 5
    assert all(s.upper().startswith("CREATE OR REPLACE VIEW") for s in stmts)


def test_drive_day_over_synthetic_layer(tiny_raw: Path, paths: RepoPaths) -> None:
    con = open_raw_layer(str(tiny_raw), paths.views_sql)
    rows = con.execute(
        "SELECT source, model, COUNT(*), SUM(failure) FROM drive_day GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    assert rows == [("alibaba", "MA1", 4, 1), ("backblaze", "A", 6, 1), ("backblaze", "B", 4, 0)]
    failed = con.execute(
        "SELECT drive_id, day FROM drive_day WHERE source = 'alibaba' AND failure = 1"
    ).fetchall()
    assert failed == [("MA1:1", date(2018, 1, 2))]


def test_compute_truth_lookup(tiny_raw: Path, paths: RepoPaths) -> None:
    con = open_raw_layer(str(tiny_raw), paths.views_sql)
    truth = compute_truth(con, _case(AFR_A))
    assert truth["drive_days"] == 6
    assert truth["failures"] == 1
    assert truth["afr_pct"] == pytest.approx(1 * 365 * 100 / 6)


def test_truth_errors(tiny_raw: Path, paths: RepoPaths) -> None:
    con = open_raw_layer(str(tiny_raw), paths.views_sql)
    with pytest.raises(TruthError, match="2 rows"):
        compute_truth(con, _case("SELECT 1.0 AS afr_pct UNION ALL SELECT 2.0"))
    with pytest.raises(TruthError, match="no column 'afr_pct'"):
        compute_truth(con, _case("SELECT 1.0 AS x"))
    with pytest.raises(TruthError, match="NULL or non-finite"):
        compute_truth(con, _case(AFR_A.replace("'A'", "'NOPE'")))
    with pytest.raises(TruthError, match="truth_sql failed"):
        compute_truth(con, _case("SELECT * FROM no_such_view"))
    ranked = _case(
        "SELECT 1.0 AS afr_pct",
        id="compare-0001",
        category="compare",
    )
    with pytest.raises(TruthError, match="no column 'model'"):
        compute_truth(con, ranked)


def test_empty_sources_get_empty_views(tmp_path: Path, paths: RepoPaths) -> None:
    raw = tmp_path / "raw"
    write_backblaze_day(raw, date(2026, 1, 1), [("A1", "A", 1, 0)])
    con = open_raw_layer(str(raw), paths.views_sql)  # no Alibaba files at all
    assert con.execute("SELECT COUNT(*) FROM drive_day WHERE source = 'alibaba'").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM drive_day").fetchone() == (1,)
    empty = open_raw_layer(str(tmp_path / "nothing"), paths.views_sql)
    assert empty.execute("SELECT COUNT(*) FROM drive_day").fetchone() == (0,)


def test_snapshot_id_tracks_file_list_and_sizes(
    tiny_raw: Path, tmp_path: Path, paths: RepoPaths
) -> None:
    con = open_raw_layer(str(tiny_raw), paths.views_sql)
    files = raw_files(con, str(tiny_raw))
    assert [f for f, _ in files][:2] == [
        "alibaba/failure_label.parquet",
        "alibaba/smart/year=2018/month=01/20180101.parquet",
    ]
    snap = snapshot_id(con, str(tiny_raw))
    assert snap.startswith("snap_")
    assert len(snap) == 21
    copy = tmp_path / "copy"
    shutil.copytree(tiny_raw, copy)
    assert snapshot_id(con, str(copy) + "/") == snap  # location-independent
    write_backblaze_day(copy, date(2026, 1, 3), [("A1", "A", 1, 0)])
    assert snapshot_id(con, str(copy)) != snap


def test_run_truth_writes_truth_and_snapshot(tiny_raw: Path, paths: RepoPaths) -> None:
    cases = [
        _case(AFR_A),
        _case("SELECT 1.0 AS nope", id="lookup-0002"),
        GoldenCase.model_validate(
            {
                "id": "out_of_scope-0001",
                "category": "out_of_scope",
                "question": "?",
                "must_refuse": True,
            }
        ),
    ]
    result = run_truth(cases, str(tiny_raw), paths.views_sql)
    assert result.computed == ["lookup-0001"]
    assert len(result.errors) == 1
    assert "lookup-0002" in result.errors[0]
    assert result.cases[0].truth is not None
    assert result.cases[0].snapshot_id == result.snapshot_id
    assert result.cases[1].truth is None  # failing case untouched
    assert result.cases[2] == cases[2]


def _binom_two_sided(k_a: int, k: int, p: float) -> float:
    """Reference two-sided exact binomial p-value (scipy.stats.binomtest semantics)."""
    pmf = [math.comb(k, i) * p**i * (1 - p) ** (k - i) for i in range(k + 1)]
    d = pmf[k_a]
    return min(1.0, sum(x for x in pmf if x <= d * (1 + 1e-7)))


def test_golden_truth_sql_binds_against_synthetic_views(tiny_raw: Path, paths: RepoPaths) -> None:
    con = open_raw_layer(str(tiny_raw), paths.views_sql)
    cases = load_cases([paths.golden_v1, paths.adversarial_cases])
    with_sql = [c for c in cases if c.truth_sql]
    assert len(with_sql) == 24
    for case in with_sql:
        explain_truth_sql(con, case)


def test_golden_truth_sql_computes_on_synthetic_data(golden_raw: Path, paths: RepoPaths) -> None:
    cases = load_cases(paths.golden_v1)
    result = run_truth(cases, str(golden_raw), paths.views_sql)
    assert result.errors == []
    assert len(result.computed) == 24
    by_id = {c.id: c for c in result.cases}

    # compare-0004 requires >= 1000 drives: only ST12000NM0008 (1,200 drives) qualifies.
    compare4 = by_id["compare-0004"].truth
    assert compare4 is not None
    assert compare4["model"] == "ST12000NM0008"

    # Trend p-value from SQL equals the exact conditional binomial test (impl-notes §4).
    for case_id in ("trend-0001", "trend-0002", "trend-0003", "trend-0004", "trend-0005"):
        t = by_id[case_id].truth
        assert t is not None
        k = t["f_later"] + t["f_earlier"]
        p0 = t["dd_later"] / (t["dd_later"] + t["dd_earlier"])
        assert t["p_value"] == pytest.approx(_binom_two_sided(t["f_later"], k, p0), rel=1e-9)
        expected_ratio = (t["f_later"] / t["dd_later"]) / (t["f_earlier"] / t["dd_earlier"])
        assert t["rate_ratio"] == pytest.approx(expected_ratio)

    for case_id in ("diagnostic-0001", "diagnostic-0004"):
        diag = by_id[case_id]
        assert diag.truth is not None
        assert diag.truth_set is not None
        assert set(diag.truth_set) <= set(diag.truth["candidates"])


def test_diagnostic_truth_set_identifies_the_driver(tmp_path: Path, paths: RepoPaths) -> None:
    """Q1: X and Y each 100 drives/day, 1 failure each. Q2: X fails 9 times, Y once.
    The whole fleet increase comes from X, so the truth set is exactly {X}."""
    raw = tmp_path / "raw"
    for day, fx, fy in ((date(2026, 1, 1), 1, 1), (date(2026, 4, 1), 9, 1)):
        rows = [(f"X{i}", "X", 1, 1 if i < fx else 0) for i in range(100)]
        rows += [(f"Y{i}", "Y", 1, 1 if i < fy else 0) for i in range(100)]
        write_backblaze_day(raw, day, rows)
    diag = next(c for c in load_cases(paths.golden_v1) if c.id == "diagnostic-0001")
    result = run_truth([diag], str(raw), paths.views_sql)
    assert result.errors == []
    assert result.cases[0].truth_set == ["X"]
    truth = result.cases[0].truth
    assert truth is not None
    assert truth["candidates"] == ["X", "Y"]
    assert truth["fleet_excess_failures"] == pytest.approx(8.0)
