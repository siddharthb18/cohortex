"""FR-EVAL-6: thresholds, regression rule, and skip-when-nothing-reviewed (impl-notes §8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cohortex_evals.gate import (
    Baseline,
    Thresholds,
    baseline_from_metrics,
    evaluate_gate,
    write_baseline,
)
from cohortex_evals.metrics import compute_metrics, percentile
from cohortex_evals.records import CaseResult, GradeResult
from cohortex_evals.settings import RepoPaths


@pytest.fixture
def thresholds(paths: RepoPaths) -> Thresholds:
    return Thresholds.load(paths.thresholds)


def _result(
    case_id: str,
    category: str = "lookup",
    *,
    reviewed: bool = True,
    numeric_ok: bool = True,
    entities: tuple[int, int] = (2, 2),
    claims: tuple[int, int] = (4, 4),
    summary: tuple[int, int] = (2, 0),
    status: str = "completed",
    refusal_ok: bool = True,
    latency: float = 10.0,
) -> CaseResult:
    grades = {"refusal": GradeResult(name="refusal", passed=refusal_ok)}
    if category in {"lookup", "compare", "trend", "ssd"}:
        grades["numeric_primary"] = GradeResult(name="numeric_primary", passed=numeric_ok)
    grades["entities"] = GradeResult(name="entities", passed=entities[0] == entities[1])
    passed = all(g.passed for g in grades.values()) and summary[1] == 0
    return CaseResult(
        case_id=case_id,
        category=category,
        reviewed=reviewed,
        must_refuse=False,
        investigation_id=f"inv-{case_id}",
        status=status,
        passed=passed,
        grades=grades,
        claims_total=claims[0],
        claims_supported=claims[1],
        summary_claims=summary[0],
        summary_leaks=summary[1],
        entities_required=entities[0],
        entities_found=entities[1],
        latency_s=latency,
        cost_usd=0.0,
    )


def _good(n: int = 10) -> list[CaseResult]:
    return [_result(f"lookup-{i:04d}") for i in range(n)]


def test_thresholds_file_matches_evaluation_spec(thresholds: Thresholds) -> None:
    m = thresholds.metrics
    assert (m["M1"].gate, m["M1"].target) == (0.85, 0.90)
    assert (m["M2"].gate, m["M2"].target) == (0.90, 0.95)
    assert (m["M3"].gate, m["M3"].target) == (0.90, 0.95)
    assert (m["M4"].op, m["M4"].gate) == ("<=", 0.0)
    assert (m["M6"].gate, m["M7"].gate, m["M8"].gate) == (0.80, 1.0, 1.0)
    assert (m["M10_p50"].target, m["M10_p95"].target) == (60, 150)
    assert thresholds.regression_points == 0.03
    assert thresholds.regression_metrics == ["M1", "M2", "M3", "M6"]


def test_gate_skipped_without_reviewed_cases(thresholds: Thresholds) -> None:
    unreviewed = [_result("lookup-0001", reviewed=False, numeric_ok=False)]
    for results in ([], unreviewed):
        gate = evaluate_gate(results, thresholds, None, "v1")
        assert gate.status == "skipped"
        assert gate.exit_code == 0


def test_gate_passes_on_good_run(thresholds: Thresholds) -> None:
    gate = evaluate_gate(_good(), thresholds, None, "v1")
    assert gate.status == "passed", gate.reasons
    assert gate.failing_cases == []


def test_gate_ignores_unreviewed_failures(thresholds: Thresholds) -> None:
    results = [*_good(), _result("lookup-0099", reviewed=False, numeric_ok=False)]
    assert evaluate_gate(results, thresholds, None, "v1").status == "passed"


def test_m1_breach_fails_and_lists_failing_cases(thresholds: Thresholds) -> None:
    results = [
        *_good(8),
        _result("lookup-0008", numeric_ok=False),
        _result("lookup-0009", numeric_ok=False),
    ]
    gate = evaluate_gate(results, thresholds, None, "v1")  # M1 = 0.8 < 0.85
    assert gate.status == "failed"
    assert gate.exit_code == 1
    assert any(r.startswith("M1") for r in gate.reasons)
    assert [(f.case_id, f.investigation_id) for f in gate.failing_cases] == [
        ("lookup-0008", "inv-lookup-0008"),
        ("lookup-0009", "inv-lookup-0009"),
    ]
    assert gate.failing_cases[0].failed == ["numeric_primary"]


def test_single_summary_leak_fails_m4(thresholds: Thresholds) -> None:
    results = [*_good(9), _result("lookup-0009", summary=(2, 1))]
    gate = evaluate_gate(results, thresholds, None, "v1")
    assert gate.status == "failed"
    assert any(r.startswith("M4") for r in gate.reasons)
    assert gate.failing_cases[0].failed == ["M4 leaks=1"]


def test_m2_m3_m7_breaches(thresholds: Thresholds) -> None:
    gate = evaluate_gate(
        [*_good(9), _result("lookup-0009", entities=(10, 0))], thresholds, None, "v1"
    )
    assert any(r.startswith("M2") for r in gate.reasons)
    gate = evaluate_gate(
        [*_good(9), _result("lookup-0009", claims=(40, 0))], thresholds, None, "v1"
    )
    assert any(r.startswith("M3") for r in gate.reasons)
    gate = evaluate_gate(
        [*_good(9), _result("lookup-0009", refusal_ok=False)], thresholds, None, "v1"
    )
    assert any(r.startswith("M7") for r in gate.reasons)


def test_target_level_checks_latency(thresholds: Thresholds) -> None:
    slow = [_result(f"lookup-{i:04d}", latency=200.0) for i in range(5)]
    assert evaluate_gate(slow, thresholds, None, "v1").status == "passed"  # no PR latency gate
    gate = evaluate_gate(slow, thresholds, None, "v1", level="target")
    assert gate.status == "failed"
    assert any(r.startswith("M10_p50") for r in gate.reasons)


def test_regression_rule(thresholds: Thresholds) -> None:
    # 9/10 numeric correct -> M1 = 0.90: above the 0.85 gate.
    results = [*_good(9), _result("lookup-0009", numeric_ok=False)]
    near = Baseline(golden_version="v1", metrics={"M1": 0.92})
    assert evaluate_gate(results, thresholds, near, "v1").status == "passed"  # -2 points
    far = Baseline(golden_version="v1", metrics={"M1": 0.94})
    gate = evaluate_gate(results, thresholds, far, "v1")  # -4 points
    assert gate.status == "failed"
    assert "M1 regressed" in gate.reasons[0]
    other_version = Baseline(golden_version="v2", metrics={"M1": 0.99})
    gate = evaluate_gate(results, thresholds, other_version, "v1")
    assert gate.status == "passed"
    assert "regression rule skipped" in gate.notes[0]
    null_baseline = Baseline(golden_version="v1", metrics={"M1": None})
    assert evaluate_gate(results, thresholds, null_baseline, "v1").status == "passed"


def test_repo_baseline_is_empty_v1(paths: RepoPaths) -> None:
    baseline = Baseline.load(paths.baseline_v1)
    assert baseline is not None
    assert baseline.golden_version == "v1"
    assert all(v is None for v in baseline.metrics.values())


def test_baseline_round_trip(tmp_path: Path, thresholds: Thresholds) -> None:
    metrics = compute_metrics(_good())
    path = tmp_path / "v1.json"
    write_baseline(path, baseline_from_metrics(metrics, thresholds, "v1", "run-1"))
    loaded = Baseline.load(path)
    assert loaded is not None
    assert loaded.metrics["M1"] == 1.0
    assert loaded.source_run == "run-1"
    assert set(loaded.metrics) == {"M1", "M2", "M3", "M6"}


def test_metric_definitions() -> None:
    results = [
        _result("lookup-0001", numeric_ok=True, entities=(2, 1), claims=(4, 3), summary=(2, 1)),
        _result("compare-0001", "compare", numeric_ok=False, entities=(2, 2), claims=(6, 6)),
        _result("diagnostic-0001", "diagnostic", entities=(2, 2), claims=(2, 1), latency=30.0),
    ]
    results[0].cost_usd = 0.002
    m = compute_metrics(results)
    assert m["M1"].value == 0.5
    assert m["M1"].denominator == 2
    assert m["M2"].value == pytest.approx(5 / 6)
    assert m["M3"].value == pytest.approx(10 / 12)
    assert (m["M4"].numerator, m["M4"].denominator) == (1, 6)
    assert m["M9"].value == pytest.approx(0.002 / 3)
    assert m["M10_p50"].value == 10.0
    assert m["M5"].value is None
    assert m["M6"].value is None


def test_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile(list(map(float, range(1, 101))), 95) == pytest.approx(95.05)
