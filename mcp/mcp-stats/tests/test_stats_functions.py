"""Statistics correctness (FR-ANA-1, implementation-notes §4)."""

import math
from typing import Any

import pytest
from cohortex_mcp_common.contracts import contracts_dir, load_json
from cohortex_mcp_stats.stats import (
    StatsInputError,
    afr_ci,
    change_point,
    compare_rates,
)

REL_TOL = 1e-9


def _fixture_cases() -> list[dict[str, Any]]:
    data = load_json(contracts_dir() / "fixtures" / "afr_ci_cases.json")
    cases: list[dict[str, Any]] = data["cases"]
    return cases


def test_afr_ci_matches_cross_language_fixture() -> None:
    cases = _fixture_cases()
    assert len(cases) == 1000
    for case in cases:
        got = afr_ci(case["failures"], case["drive_days"], case["confidence"])
        for key in ("afr_pct", "ci_low_pct", "ci_high_pct"):
            assert math.isclose(got[key], case[key], rel_tol=REL_TOL, abs_tol=0.0), (case, key)
        assert got["method"] == "exact_poisson_95"


def test_afr_ci_zero_failures_has_zero_lower_bound() -> None:
    got = afr_ci(0, 98189)
    assert got["afr_pct"] == 0.0
    assert got["ci_low_pct"] == 0.0
    assert got["ci_high_pct"] > 0.0


def test_afr_ci_other_confidence_names_method() -> None:
    narrow = afr_ci(10, 100_000, 0.9)
    wide = afr_ci(10, 100_000, 0.99)
    assert narrow["method"] == "exact_poisson_90"
    assert wide["method"] == "exact_poisson_99"
    assert wide["ci_low_pct"] < narrow["ci_low_pct"] < narrow["ci_high_pct"] < wide["ci_high_pct"]


def test_compare_rates_known_binomtest_value() -> None:
    # Equal exposure => p0 = 0.5; scipy.stats.binomtest(7, 20, 0.5).pvalue = 0.26317596435546875
    got = compare_rates(7, 1000, 13, 1000)
    assert math.isclose(got["p_value"], 0.26317596435546875, rel_tol=1e-12)
    assert math.isclose(got["rate_ratio"], 7 / 13, rel_tol=1e-12)
    assert got["ci_low"] < got["rate_ratio"] < got["ci_high"]
    assert got["method"] == "exact_conditional_binomial"


def test_compare_rates_unequal_exposure() -> None:
    # binomtest(30, 42, 1e6/2.1e6): two-sided p-value computed with scipy 1.18.1
    got = compare_rates(30, 1_000_000, 12, 1_100_000)
    assert math.isclose(got["rate_ratio"], (30 / 1_000_000) / (12 / 1_100_000), rel_tol=1e-12)
    assert math.isclose(got["p_value"], 0.002856101413509721, rel_tol=1e-9)
    assert math.isclose(got["ci_low"], 1.3672594485683671, rel_tol=1e-9)
    assert math.isclose(got["ci_high"], 5.897835331858538, rel_tol=1e-9)


def test_compare_rates_equal_rates_is_not_significant() -> None:
    got = compare_rates(10, 5000, 20, 10000)
    assert got["rate_ratio"] == pytest.approx(1.0)
    assert got["p_value"] == pytest.approx(1.0)


def test_compare_rates_unbounded_ratio_is_null() -> None:
    got = compare_rates(5, 1000, 0, 1000)
    assert got["rate_ratio"] is None
    assert got["ci_high"] is None
    assert got["ci_low"] is not None
    zero_a = compare_rates(0, 1000, 5, 1000)
    assert zero_a["rate_ratio"] == 0.0
    assert zero_a["ci_low"] == 0.0


def test_compare_rates_needs_a_failure() -> None:
    with pytest.raises(StatsInputError):
        compare_rates(0, 1000, 0, 1000)


def _step_series(n: int, step_at: int, before: int, after: int) -> list[dict[str, Any]]:
    return [
        {
            "period": f"2025-{i + 1:02d}" if i < 12 else f"2026-{i - 11:02d}",
            "failures": before if i < step_at else after,
            "drive_days": 100_000,
        }
        for i in range(n)
    ]


def test_change_point_finds_synthetic_step() -> None:
    series = _step_series(12, 7, before=5, after=20)
    got = change_point(series)
    assert got["change_period"] == "2025-08"
    assert got["change_index"] == 7
    assert got["p_value"] <= 0.01
    assert got["afr_after_pct"] > got["afr_before_pct"]
    assert got["rate_ratio"] == pytest.approx(4.0)
    assert got["bootstrap_draws"] == 999


def test_change_point_is_deterministic() -> None:
    series = _step_series(10, 4, before=8, after=11)
    assert change_point(series) == change_point(series)


def test_change_point_flat_series_is_not_significant() -> None:
    got = change_point(_step_series(12, 0, before=10, after=10))
    assert got["p_value"] > 0.2


def test_change_point_no_failures() -> None:
    got = change_point(_step_series(6, 0, before=0, after=0))
    assert got["change_period"] is None
    assert got["statistic"] == 0.0
    assert got["p_value"] == 1.0


@pytest.mark.parametrize(
    "periods",
    [
        ["2025-02", "2025-01", "2025-03"],  # out of order
        ["2025-01", "2025-01", "2025-02"],  # duplicate
        ["2025Q1", "2025-02", "2025-03"],  # mixed labels
    ],
)
def test_change_point_rejects_bad_period_order(periods: list[str]) -> None:
    series = [{"period": p, "failures": 1, "drive_days": 10} for p in periods]
    with pytest.raises(StatsInputError):
        change_point(series)
