"""Pure statistics behind the stats tools (implementation-notes §4).

- ``afr_ci``: AFR with the exact Poisson interval (chi-square form), identical to fleet-api's Java
  implementation; checked against ``contracts/fixtures/afr_ci_cases.json`` to 1e-9 (FR-ANA-1).
- ``compare_rates``: exact conditional binomial test of two Poisson rates.
- ``change_point``: single change point in a Poisson rate series, likelihood-ratio statistic,
  p-value by parametric bootstrap (999 draws, seed 7) so results are reproducible.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

import numpy as np
from scipy import special, stats  # type: ignore[import-untyped]

DAYS_PER_YEAR = 365
BOOTSTRAP_DRAWS = 999
BOOTSTRAP_SEED = 7
_TIE_TOLERANCE = 1e-9
_PERIOD_KINDS = (
    ("quarter", re.compile(r"^\d{4}Q[1-4]$")),
    ("month", re.compile(r"^\d{4}-\d{2}$")),
    ("day", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
)


class StatsInputError(ValueError):
    """Arguments are well-formed but cannot be computed on (reported as ``invalid_argument``)."""


def _pct_per_year(count: float, drive_days: float) -> float:
    """Count over drive-days as percent per year: ``count * 365 * 100 / drive_days``."""
    return count * DAYS_PER_YEAR * 100 / drive_days


def _method_suffix(confidence: float) -> str:
    return f"{round(confidence * 100, 6):g}"


def afr_ci(failures: int, drive_days: int, confidence: float = 0.95) -> dict[str, Any]:
    """AFR in percent per year with the exact Poisson interval.

    Lower count ``chi2.ppf(a, 2k) / 2`` (0 when k = 0), upper count ``chi2.ppf(1 - a, 2k + 2) / 2``,
    ``a = (1 - confidence) / 2``; both converted with the AFR factor.
    """
    alpha = (1 - confidence) / 2
    lower = 0.0 if failures == 0 else float(stats.chi2.ppf(alpha, 2 * failures)) / 2
    upper = float(stats.chi2.ppf(1 - alpha, 2 * failures + 2)) / 2
    return {
        "afr_pct": _pct_per_year(failures, drive_days),
        "ci_low_pct": _pct_per_year(lower, drive_days),
        "ci_high_pct": _pct_per_year(upper, drive_days),
        "confidence": confidence,
        "method": f"exact_poisson_{_method_suffix(confidence)}",
    }


def _ratio_from_proportion(p: float, drive_days_a: int, drive_days_b: int) -> float | None:
    if p >= 1.0:
        return None  # unbounded
    return p / (1 - p) * drive_days_b / drive_days_a


def compare_rates(
    failures_a: int, drive_days_a: int, failures_b: int, drive_days_b: int
) -> dict[str, Any]:
    """Exact conditional binomial test of rate A vs rate B.

    Given ``k = ka + kb``, under H0 ``ka ~ Binomial(k, p0)`` with ``p0 = dda / (dda + ddb)``.
    The ratio's 95% interval maps the Clopper-Pearson interval on ``p`` by
    ``p / (1 - p) * ddb / dda``. ``None`` means unbounded (``kb = 0``).
    """
    total = failures_a + failures_b
    if total == 0:
        raise StatsInputError("compare_rates needs at least one failure across both groups")
    p0 = drive_days_a / (drive_days_a + drive_days_b)
    result = stats.binomtest(failures_a, total, p0, alternative="two-sided")
    interval = result.proportion_ci(confidence_level=0.95, method="exact")
    rate_ratio = (
        None if failures_b == 0 else (failures_a / drive_days_a) / (failures_b / drive_days_b)
    )
    return {
        "rate_ratio": rate_ratio,
        "ci_low": _ratio_from_proportion(float(interval.low), drive_days_a, drive_days_b),
        "ci_high": _ratio_from_proportion(float(interval.high), drive_days_a, drive_days_b),
        "p_value": float(result.pvalue),
        "method": "exact_conditional_binomial",
    }


def _check_periods(periods: Sequence[str]) -> None:
    kinds = set()
    for period in periods:
        kind = next((name for name, rx in _PERIOD_KINDS if rx.fullmatch(period)), None)
        if kind is None:
            raise StatsInputError("series periods must be YYYYQn, YYYY-MM or YYYY-MM-DD")
        kinds.add(kind)
    if len(kinds) != 1:
        raise StatsInputError("series periods must all use the same label format")
    if any(a >= b for a, b in pairwise(periods)):
        raise StatsInputError("series periods must be unique and in increasing time order")


def _split_statistics(counts: Any, exposures: Any) -> Any:
    """2 x log-likelihood gain of a split after each position, for each row of ``counts``.

    ``counts`` has shape (rows, n); returns shape (rows, n - 1). Poisson terms that do not depend
    on the rates cancel between H0 and H1.
    """
    k_left = np.cumsum(counts, axis=1)[:, :-1]
    d_left = np.cumsum(exposures)[:-1]
    k_total = counts.sum(axis=1, keepdims=True)
    d_total = float(exposures.sum())
    k_right = k_total - k_left
    d_right = d_total - d_left
    gain = (
        special.xlogy(k_left, k_left / d_left)
        + special.xlogy(k_right, k_right / d_right)
        - special.xlogy(k_total, k_total / d_total)
    )
    return np.maximum(2.0 * gain, 0.0)


def change_point(series: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Most likely single change in a Poisson failure rate.

    ``change_index`` is the position of the first period at the new rate. The p-value is
    ``(1 + #{T* >= T}) / (B + 1)`` over B = 999 bootstrap series drawn under a constant rate with a
    fixed seed (7), so the same input always gives the same p-value.
    """
    periods = [str(point["period"]) for point in series]
    _check_periods(periods)
    counts = np.array([[int(p["failures"]) for p in series]], dtype=np.float64)
    exposures = np.array([float(p["drive_days"]) for p in series], dtype=np.float64)
    n = len(periods)
    total_failures = float(counts.sum())
    base = {
        "n_points": n,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "method": "poisson_single_change_lrt_bootstrap",
    }
    if total_failures == 0:
        return {
            "change_period": None,
            "change_index": None,
            "statistic": 0.0,
            "p_value": 1.0,
            "afr_before_pct": 0.0,
            "afr_after_pct": 0.0,
            "rate_ratio": None,
            **base,
        }

    observed = _split_statistics(counts, exposures)[0]
    split = int(np.argmax(observed))  # split after position `split`
    statistic = float(observed[split])

    rate = total_failures / float(exposures.sum())
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.poisson(rate * exposures, size=(BOOTSTRAP_DRAWS, n)).astype(np.float64)
    simulated = _split_statistics(draws, exposures).max(axis=1)
    exceed = int(np.count_nonzero(simulated >= statistic - _TIE_TOLERANCE))
    p_value = (1 + exceed) / (BOOTSTRAP_DRAWS + 1)

    index = split + 1
    before = _pct_per_year(float(counts[0, :index].sum()), float(exposures[:index].sum()))
    after = _pct_per_year(float(counts[0, index:].sum()), float(exposures[index:].sum()))
    return {
        "change_period": periods[index],
        "change_index": index,
        "statistic": statistic,
        "p_value": p_value,
        "afr_before_pct": before,
        "afr_after_pct": after,
        "rate_ratio": None if before == 0 else after / before,
        **base,
    }
