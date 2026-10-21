"""CI gate (FR-EVAL-6): thresholds from evaluation spec §1 plus the regression rule."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from cohortex_evals.metrics import Metric, compute_metrics
from cohortex_evals.records import CaseResult

Level = Literal["gate", "target"]


class Threshold(BaseModel):
    name: str
    op: Literal[">=", "<="]
    gate: float | None = None  # "Gate on PRs (recorded)"
    target: float | None = None  # "Target (nightly live)"
    phase: str = "MVP"
    enforce: bool = True


class Thresholds(BaseModel):
    golden_version: str
    regression_points: float
    regression_metrics: list[str]
    metrics: dict[str, Threshold]

    @classmethod
    def load(cls, path: Path) -> Thresholds:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class Baseline(BaseModel):
    golden_version: str
    metrics: dict[str, float | None] = Field(default_factory=dict)
    source_run: str | None = None
    note: str = ""

    @classmethod
    def load(cls, path: Path) -> Baseline | None:
        if not path.is_file():
            return None
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class MetricCheck(BaseModel):
    metric: str
    name: str
    value: float | None
    op: str
    limit: float | None
    passed: bool | None  # None = not checked (no limit, not enforced, or no data)
    reason: str = ""


class FailingCase(BaseModel):
    case_id: str
    category: str
    investigation_id: str | None
    status: str
    failed: list[str]


class GateResult(BaseModel):
    status: Literal["passed", "failed", "skipped"]
    level: Level
    golden_version: str
    reviewed_cases: int
    reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    checks: list[MetricCheck] = Field(default_factory=list)
    metrics: dict[str, Metric] = Field(default_factory=dict)
    failing_cases: list[FailingCase] = Field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


def _check(metric_id: str, t: Threshold, m: Metric | None, level: Level) -> MetricCheck:
    limit = t.gate if level == "gate" else t.target
    value = m.value if m is not None else None
    check = MetricCheck(
        metric=metric_id, name=t.name, value=value, op=t.op, limit=limit, passed=None
    )
    if limit is None:
        check.reason = f"no {level} threshold"
    elif not t.enforce:
        check.reason = "not enforced"
    elif value is None:
        check.reason = "no applicable cases"
    else:
        check.passed = value >= limit if t.op == ">=" else value <= limit
    return check


def failing_cases(results: Sequence[CaseResult]) -> list[FailingCase]:
    out: list[FailingCase] = []
    for r in results:
        if r.passed:
            continue
        failed = r.failed_graders()
        if r.summary_leaks:
            failed.append(f"M4 leaks={r.summary_leaks}")
        out.append(
            FailingCase(
                case_id=r.case_id,
                category=r.category,
                investigation_id=r.investigation_id,
                status=r.status,
                failed=failed or [r.error or "failed"],
            )
        )
    return out


def evaluate_gate(
    results: Sequence[CaseResult],
    thresholds: Thresholds,
    baseline: Baseline | None,
    golden_version: str,
    level: Level = "gate",
) -> GateResult:
    """Gate over *reviewed* cases only; with none, the gate is skipped (impl-notes §8)."""
    reviewed = [r for r in results if r.reviewed]
    gate = GateResult(
        status="passed", level=level, golden_version=golden_version, reviewed_cases=len(reviewed)
    )
    if not reviewed:
        gate.status = "skipped"
        gate.notes.append("no reviewed golden cases in this run; gate skipped")
        return gate

    metrics = compute_metrics(reviewed)
    gate.metrics = metrics
    for metric_id, threshold in thresholds.metrics.items():
        check = _check(metric_id, threshold, metrics.get(metric_id), level)
        gate.checks.append(check)
        if check.passed is False:
            gate.reasons.append(
                f"{metric_id} {threshold.name} = {check.value:.4g} "
                f"breaches {check.op} {check.limit:g}"
            )

    if baseline is None:
        gate.notes.append("no baseline file; regression rule skipped")
    elif baseline.golden_version != golden_version:
        gate.notes.append(
            f"baseline is for golden set {baseline.golden_version}, run is {golden_version}; "
            "regression rule skipped"
        )
    else:
        for metric_id in thresholds.regression_metrics:
            base = baseline.metrics.get(metric_id)
            current = metrics[metric_id].value if metric_id in metrics else None
            if base is None or current is None:
                continue
            if current < base - thresholds.regression_points:
                gate.reasons.append(
                    f"{metric_id} regressed: {current:.4f} vs baseline {base:.4f} "
                    f"(more than {thresholds.regression_points * 100:g} points)"
                )

    gate.failing_cases = failing_cases(reviewed)
    gate.status = "failed" if gate.reasons else "passed"
    return gate


def baseline_from_metrics(
    metrics: dict[str, Metric], thresholds: Thresholds, golden_version: str, source_run: str
) -> Baseline:
    return Baseline(
        golden_version=golden_version,
        metrics={
            m: metrics[m].value if m in metrics else None for m in thresholds.regression_metrics
        },
        source_run=source_run,
        note="Written by `cohortex-eval gate --update-baseline`; change only in a dedicated PR.",
    )


def write_baseline(path: Path, baseline: Baseline) -> None:
    path.write_text(
        json.dumps(baseline.model_dump(mode="json"), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
