"""Serializable records passed between runner, graders, metrics, gate and reports."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CaseRun(BaseModel):
    """What the runner observed for one case (everything graders need, so grading is offline)."""

    case_id: str
    investigation_id: str | None = None
    # A terminal investigation status, or ``timeout`` / ``error`` when the harness gave up.
    status: str
    error: str | None = None
    latency_s: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    llm_model: str | None = None
    report: dict[str, Any] | None = None
    markdown: str | None = None
    # Evidence fetched for summary claims: evidence_id -> GET .../evidence/{id} body.
    evidence: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Evidence IDs cited in the summary that could not be fetched: id -> reason.
    evidence_errors: dict[str, str] = Field(default_factory=dict)


class GradeResult(BaseModel):
    name: str
    passed: bool
    score: float | None = None
    detail: str = ""


class CaseResult(BaseModel):
    """One graded case, as stored in the run JSON and ``eval_case_result.scores``."""

    case_id: str
    category: str
    reviewed: bool
    must_refuse: bool
    investigation_id: str | None = None
    status: str
    passed: bool
    grades: dict[str, GradeResult] = Field(default_factory=dict)
    # Counters for micro-averaged metrics.
    claims_total: int = 0
    claims_supported: int = 0
    summary_claims: int = 0
    summary_leaks: int = 0
    leak_details: list[str] = Field(default_factory=list)
    entities_required: int = 0
    entities_found: int = 0
    latency_s: float | None = None
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    llm_model: str | None = None
    error: str | None = None

    def failed_graders(self) -> list[str]:
        return [name for name, g in self.grades.items() if not g.passed]
