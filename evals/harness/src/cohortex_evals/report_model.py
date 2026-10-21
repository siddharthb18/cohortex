"""Lenient mirror of the agent-service investigation and Report (contracts §6, impl-notes §7).

The harness reads reports produced by another service, so parsing is tolerant: missing lists
default to empty and unknown fields are ignored. Graders decide what is wrong, not the parser.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

TERMINAL_STATUSES = frozenset({"completed", "failed", "budget_exceeded", "refused"})


class NumberRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: float
    unit: str
    evidence_id: str = ""
    field: str = ""


class Claim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    numbers: list[NumberRef] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)
    status: str = "unsupported"


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statement: str = ""
    support: list[Claim] = Field(default_factory=list)
    confidence: str | None = None
    how_to_confirm: str = ""


class Report(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = ""
    scope: dict[str, Any] | None = None
    summary: list[Claim] = Field(default_factory=list)
    findings: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    unverified: list[Claim] = Field(default_factory=list)
    mode: str | None = None
    model_id: str | None = None
    prompt_hashes: dict[str, str] = Field(default_factory=dict)

    def all_claims(self) -> list[Claim]:
        """Every distinct claim in the report (summary repeats findings, so dedupe by text)."""
        seen: set[str] = set()
        out: list[Claim] = []
        groups = [self.summary, self.findings, self.unverified]
        groups.extend(h.support for h in self.hypotheses)
        for group in groups:
            for claim in group:
                key = claim.text.strip()
                if key in seen:
                    continue
                seen.add(key)
                out.append(claim)
        return out

    def answer_text(self) -> str:
        """Text the answer consists of: summary, findings and hypotheses (not unverified claims)."""
        parts = [c.text for c in self.summary]
        parts += [c.text for c in self.findings]
        for h in self.hypotheses:
            parts.append(h.statement)
            parts += [c.text for c in h.support]
        parts += self.recommended_actions
        return "\n".join(parts)

    def headline_text(self) -> str:
        """Text where the report *names* its conclusion: summary and hypotheses."""
        parts = [c.text for c in self.summary]
        for h in self.hypotheses:
            parts.append(h.statement)
            parts += [c.text for c in h.support]
        return "\n".join(parts)


class Investigation(BaseModel):
    """``GET /v1/investigations/{id}`` (implementation-notes §7)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    status: str
    question: str | None = None
    scope: dict[str, Any] | None = None
    mode: str | None = None
    llm_model: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    report: dict[str, Any] | None = None
    markdown: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def parse_report(raw: dict[str, Any] | None) -> Report | None:
    if raw is None:
        return None
    return Report.model_validate(raw)
