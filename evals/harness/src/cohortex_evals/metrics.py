"""Run-level metrics M1-M10 (evaluation spec §1) from graded case results."""

from __future__ import annotations

import math
from collections.abc import Sequence

from pydantic import BaseModel

from cohortex_evals.cases import IN_SCOPE_CATEGORIES, NUMERIC_CATEGORIES
from cohortex_evals.records import CaseResult

SUCCESS_STATUSES = frozenset({"completed", "refused"})


class Metric(BaseModel):
    value: float | None
    numerator: float | None = None
    denominator: int = 0
    note: str = ""


def _ratio(num: float, den: int, note: str = "") -> Metric:
    return Metric(value=num / den if den else None, numerator=num, denominator=den, note=note)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in [0, 100])."""
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100.0
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _grader_rate(results: Sequence[CaseResult], grader: str, note: str) -> Metric:
    graded = [r.grades[grader] for r in results if grader in r.grades]
    return _ratio(sum(1 for g in graded if g.passed), len(graded), note)


def compute_metrics(results: Sequence[CaseResult]) -> dict[str, Metric]:
    numeric = [r for r in results if r.category in NUMERIC_CATEGORIES]
    m1_pass = sum(
        1 for r in numeric if "numeric_primary" in r.grades and r.grades["numeric_primary"].passed
    )
    in_scope = [r for r in results if r.category in IN_SCOPE_CATEGORIES]
    recalls = [
        r.grades["retrieval_recall"].score
        for r in results
        if "retrieval_recall" in r.grades and r.grades["retrieval_recall"].score is not None
    ]
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    latencies = [r.latency_s for r in results if r.latency_s is not None]
    summary_claims = sum(r.summary_claims for r in results)
    leaks = sum(r.summary_leaks for r in results)

    metrics: dict[str, Metric] = {
        "M1": _ratio(m1_pass, len(numeric), "numeric cases within tolerance"),
        "M2": _ratio(
            sum(r.entities_found for r in in_scope),
            sum(r.entities_required for r in in_scope),
            "required entities present",
        ),
        "M3": _ratio(
            sum(r.claims_supported for r in results),
            sum(r.claims_total for r in results),
            "claims marked supported / all claims",
        ),
        "M4": Metric(
            value=leaks / summary_claims if summary_claims else (0.0 if results else None),
            numerator=leaks,
            denominator=summary_claims,
            note="summary claims failing the independent recheck",
        ),
        "M5": Metric(value=None, note="faithfulness judge not validated yet (Phase 3)"),
        "M6": Metric(
            value=sum(recalls) / len(recalls) if recalls else None,
            numerator=sum(recalls),
            denominator=len(recalls),
            note="mean recall@5 over labeled literature cases",
        ),
        "M7": _grader_rate(results, "refusal", "status refused exactly when must_refuse"),
        "M8": _grader_rate(results, "injection", "adversarial cases resisted"),
        "M9": Metric(
            value=sum(costs) / len(costs) if costs else None,
            numerator=sum(costs),
            denominator=len(costs),
            note="mean USD per investigation",
        ),
        "M10_p50": Metric(
            value=percentile(latencies, 50), denominator=len(latencies), note="seconds"
        ),
        "M10_p95": Metric(
            value=percentile(latencies, 95), denominator=len(latencies), note="seconds"
        ),
        "REL1": _ratio(
            sum(1 for r in results if r.status in SUCCESS_STATUSES),
            len(results),
            "NFR-REL-1: report produced, not budget-killed",
        ),
    }
    return metrics
