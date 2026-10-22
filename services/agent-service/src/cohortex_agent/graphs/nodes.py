"""Nodes shared by both modes: scope guard, drafter, checker, reporter (ADR-006).

Both modes end in the same drafter -> checker -> (revise <= 2) -> reporter tail, with the same
ledger, checker and report schema, so the two modes compare fairly.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from cohortex_agent.checker import check_draft
from cohortex_agent.graphs.context import RunContext, data_block, scope_dict, to_json
from cohortex_agent.graphs.state import GraphState
from cohortex_agent.llm.base import Message, StructuredOutputError
from cohortex_agent.report import assemble_report
from cohortex_agent.schemas import DraftOutput, Plan, Report, Scope, ScopeDecision

logger = logging.getLogger(__name__)

MAX_REVISIONS = 2


class Node(Protocol):
    def __call__(self, state: GraphState) -> Awaitable[dict[str, Any]]: ...


PURCHASE_ADVICE = re.compile(
    r"\b(buy|buying|purchase|purchasing|shopping|procure|procurement|vendor to choose)\b",
    re.IGNORECASE,
)
PURCHASE_REASON = (
    "Purchase advice is out of scope: Cohortex analyzes public fleet reliability data and does "
    "not recommend drives to buy."
)
DEFAULT_REFUSAL = "This question is outside Cohortex's scope (drive-fleet reliability data)."


def rule_refusal(question: str) -> str | None:
    """Cheap deterministic pre-check before the LLM classifier (FR-AGT-10)."""
    if PURCHASE_ADVICE.search(question):
        return PURCHASE_REASON
    return None


def one_line(text: str, limit: int = 200) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def question_message(ctx: RunContext, extra: str = "") -> Message:
    scope = scope_dict(ctx.scope)
    body = f"Question: {ctx.question}\nScope: {to_json(scope) if scope else 'not specified'}"
    return {"role": "user", "content": body + (f"\n\n{extra}" if extra else "")}


def make_guard(ctx: RunContext) -> Node:
    async def guard(state: GraphState) -> dict[str, Any]:
        reason = rule_refusal(ctx.question)
        if reason is None:
            messages: list[Message] = [
                {"role": "system", "content": ctx.prompts.text("refusal")},
                {
                    "role": "user",
                    "content": data_block(
                        "question_to_classify",
                        {"question": ctx.question, "scope": scope_dict(ctx.scope)},
                    ),
                },
            ]
            try:
                decision, _ = await ctx.structured("guard", messages, ScopeDecision)
            except StructuredOutputError:
                # Fail open: a broken classifier must not block in-scope work; the drafter and
                # checker still constrain what an out-of-scope run could report.
                logger.warning("scope guard output invalid; treating question as in scope")
                decision = ScopeDecision(in_scope=True)
            if not decision.in_scope:
                reason = decision.reason or DEFAULT_REFUSAL
        if reason is not None:
            return {"status": "refused", "refusal_reason": one_line(reason)}
        return {"status": "running"}

    return guard


def route_after_guard(next_node: str) -> Callable[[GraphState], str]:
    def route(state: GraphState) -> str:
        return "reporter" if state.get("status") == "refused" else next_node

    return route


def make_drafter(ctx: RunContext) -> Node:
    async def drafter(state: GraphState) -> dict[str, Any]:
        material: dict[str, Any] = {
            "notes": state.get("notes", []),
            "evidence": ctx.evidence_for_model(),
        }
        if state.get("plan"):
            material["plan"] = state["plan"]
        messages: list[Message] = [
            {"role": "system", "content": ctx.prompts.text("drafter")},
            question_message(ctx, data_block("investigation_material", material)),
        ]
        revising = bool(state.get("unsupported_notes")) and bool(state.get("draft_text"))
        if revising:
            messages += [
                {"role": "assistant", "content": state["draft_text"]},
                {
                    "role": "user",
                    "content": ctx.prompts.text("revise")
                    + "\n\n"
                    + data_block("checker_notes", state["unsupported_notes"]),
                },
            ]
        try:
            draft, raw = await ctx.structured("drafter", messages, DraftOutput)
        except StructuredOutputError:
            if revising and ctx.last_check is not None:
                logger.warning("revision output invalid; keeping the previous checked draft")
                return {"draft_text": state["draft_text"], "unsupported_notes": []}
            raise
        draft = ctx.resolve_aliases(draft)
        await ctx.ledger.step(
            "drafter",
            "draft",
            {"claims": [c.model_dump(mode="json") for c in draft.all_claims()]},
        )
        return {"draft": draft.model_dump(mode="json"), "draft_text": raw}

    return drafter


def make_checker(ctx: RunContext) -> Node:
    async def checker(state: GraphState) -> dict[str, Any]:
        draft = DraftOutput.model_validate(state["draft"])
        check = check_draft(draft, ctx.ledger.evidence)
        ctx.last_check = check
        notes = check.notes()
        await ctx.ledger.step(
            "checker",
            "check",
            {"supported": check.supported, "unsupported": len(check.unsupported), "notes": notes},
        )
        revisions = state.get("revisions", 0)
        revise = bool(check.unsupported) and revisions < MAX_REVISIONS
        return {
            "unsupported_notes": [ctx.to_aliases(n) for n in notes] if revise else [],
            "revisions": revisions + 1 if revise else revisions,
        }

    return checker


def route_after_check(state: GraphState) -> str:
    return "drafter" if state.get("unsupported_notes") else "reporter"


def report_scope(ctx: RunContext, plan: dict[str, Any] | None) -> Scope:
    if ctx.scope.model_dump(exclude_defaults=True) or not plan:
        return ctx.scope
    return Plan.model_validate(plan).scope


def build_report(ctx: RunContext, state: GraphState, status: str) -> Report:
    if status == "refused":
        return Report(
            question=ctx.question,
            scope=ctx.scope,
            summary=[],
            findings=[],
            hypotheses=[],
            recommended_actions=[],
            limitations=[f"Refused: {state.get('refusal_reason') or DEFAULT_REFUSAL}"],
            unverified=[],
            mode=ctx.mode,  # type: ignore[arg-type]
            model_id=ctx.provider.model_id,
            prompt_hashes=ctx.prompts.hashes(ctx.mode),
        )
    limitation = ctx.budget.limitation()
    return assemble_report(
        question=ctx.question,
        scope=report_scope(ctx, state.get("plan")),
        mode=ctx.mode,
        model_id=ctx.provider.model_id,
        prompt_hashes=ctx.prompts.hashes(ctx.mode),
        checked=ctx.last_check,
        evidence=ctx.ledger.evidence,
        extra_limitations=[limitation] if limitation else [],
    )


def make_reporter(ctx: RunContext) -> Node:
    async def reporter(state: GraphState) -> dict[str, Any]:
        if state.get("status") == "refused":
            status = "refused"
        elif ctx.budget.tool_limit_hit:
            status = "budget_exceeded"
        else:
            status = "completed"
        report = build_report(ctx, state, status)
        return {"status": status, "report": report.model_dump(mode="json")}

    return reporter
