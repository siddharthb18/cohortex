"""Pydantic models.

The first block is docs/specs/contracts.md §6 verbatim: it is the contract between graph nodes and
the source of `contracts/report/report.schema.json`. Everything after it is agent-service internal
(drafter output) or HTTP API shapes (docs/implementation-notes.md §7).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------------------------
# contracts.md §6 (verbatim)
# --------------------------------------------------------------------------------------------


class Scope(BaseModel):
    source: Literal["backblaze", "alibaba"] | None = None
    models: list[str] = Field(default_factory=list, max_length=10)
    date_from: date | None = None
    date_to: date | None = None


class Task(BaseModel):
    id: str  # t1..t6
    kind: Literal["data", "literature", "stats"]
    goal: str = Field(max_length=300)
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    restated_question: str
    scope: Scope
    tasks: list[Task] = Field(min_length=1, max_length=6)


class NumberRef(BaseModel):
    value: float
    unit: Literal["pct", "count", "drive_days", "days", "ratio", "p_value", "raw"]
    evidence_id: str
    field: str  # JSON path in the evidence data, e.g. series[0].afr_pct


class Claim(BaseModel):
    text: str = Field(max_length=500)
    numbers: list[NumberRef] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)
    status: Literal["supported", "unsupported"] = "unsupported"


class Hypothesis(BaseModel):
    statement: str
    support: list[Claim]
    confidence: Literal["low", "medium", "high"]
    how_to_confirm: str  # what data or test would settle it


class Report(BaseModel):
    question: str
    scope: Scope
    summary: list[Claim] = Field(max_length=5)  # supported claims only
    findings: list[Claim]
    hypotheses: list[Hypothesis] = Field(max_length=4)
    recommended_actions: list[str] = Field(max_length=5)
    limitations: list[str]  # includes triggered dataset caveats
    unverified: list[Claim]  # failed the evidence check
    mode: Literal["single", "orchestrated"]
    model_id: str
    prompt_hashes: dict[str, str]


class InvestigationState(BaseModel):  # LangGraph state
    investigation_id: str
    question: str
    plan: Plan | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    draft: list[Claim] = Field(default_factory=list)
    revisions: int = 0  # max 2
    tool_calls: int = 0  # max 20
    input_tokens: int = 0  # max 150_000
    report: Report | None = None
    status: Literal["running", "completed", "failed", "budget_exceeded", "refused"] = "running"


# --------------------------------------------------------------------------------------------
# agent-service internal: structured LLM outputs
# --------------------------------------------------------------------------------------------

_DRAFT_LIMITS = {"summary": 5, "hypotheses": 4, "recommended_actions": 5}


class DraftOutput(BaseModel):
    """What the drafter returns. Over-long lists are truncated rather than rejected."""

    summary: list[Claim] = Field(default_factory=list, max_length=5)
    findings: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=4)
    recommended_actions: list[str] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _truncate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for key, limit in _DRAFT_LIMITS.items():
                value = data.get(key)
                if isinstance(value, list) and len(value) > limit:
                    data[key] = value[:limit]
        return data

    def all_claims(self) -> list[Claim]:
        claims = [*self.summary, *self.findings]
        for hypothesis in self.hypotheses:
            claims.extend(hypothesis.support)
        return claims


class ScopeDecision(BaseModel):
    """Output of the refusal (scope guard) classifier."""

    in_scope: bool
    reason: str = Field(default="", max_length=300)


# --------------------------------------------------------------------------------------------
# HTTP API (contracts.md §4, implementation-notes.md §7)
# --------------------------------------------------------------------------------------------

InvestigationStatus = Literal[
    "queued", "running", "completed", "failed", "budget_exceeded", "refused"
]
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "budget_exceeded", "refused"})


class ScopeIn(BaseModel):
    """API scope: accepts `from`/`to` (contracts §4) or `date_from`/`date_to` (golden set)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: Literal["backblaze", "alibaba"] | None = None
    models: list[str] = Field(default_factory=list, max_length=10)
    date_from: date | None = Field(default=None, validation_alias=AliasChoices("from", "date_from"))
    date_to: date | None = Field(default=None, validation_alias=AliasChoices("to", "date_to"))

    def to_scope(self) -> Scope:
        return Scope(
            source=self.source,
            models=list(self.models),
            date_from=self.date_from,
            date_to=self.date_to,
        )


class InvestigationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=1000)
    scope: ScopeIn | None = None
    mode: Literal["single", "orchestrated"] | None = None


class InvestigationCreated(BaseModel):
    id: str
    status: InvestigationStatus


class InvestigationView(BaseModel):
    id: str
    question: str
    scope: dict[str, Any] | None
    mode: Literal["single", "orchestrated"]
    status: InvestigationStatus
    llm_model: str
    started_at: datetime
    finished_at: datetime | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    report: Report | None
    markdown: str | None


class InvestigationSummary(BaseModel):
    id: str
    question: str
    mode: Literal["single", "orchestrated"]
    status: InvestigationStatus
    started_at: datetime
    finished_at: datetime | None


class StepView(BaseModel):
    seq: int
    node: str
    kind: Literal["plan", "tool_call", "draft", "check", "report", "error"]
    payload: dict[str, Any]
    started_at: datetime
    ended_at: datetime | None


class EvidenceView(BaseModel):
    evidence_id: str
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    created_at: datetime


class SuggestedAlert(BaseModel):
    alert_id: str
    source: str
    model: str
    opened_at: datetime
    window_start: date
    window_end: date
    baseline_afr: float
    current_afr: float
    rate_ratio: float
    p_value: float
    suggested_question: str
    suggested_scope: Scope
