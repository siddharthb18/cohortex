"""`run_investigation(question, scope, mode)`: the one entry point to both graphs (ADR-006).

The runner owns everything around a graph run: the investigation row and its status, the budget
and wall-time guard, partial reports on budget stops, typed failures, claim rows, the final
`report` step, and the terminal SSE event.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from cohortex_agent.budget import Budget, BudgetExceeded
from cohortex_agent.config import Settings
from cohortex_agent.db import Database
from cohortex_agent.events import EventBus
from cohortex_agent.graphs import RunContext, build_graph
from cohortex_agent.graphs.nodes import build_report
from cohortex_agent.ledger import Ledger
from cohortex_agent.llm.base import LLMProvider
from cohortex_agent.prompts import PromptStore
from cohortex_agent.report import render_markdown
from cohortex_agent.schemas import Claim, Report, Scope
from cohortex_agent.tools.base import ToolGateway

logger = logging.getLogger(__name__)
RECURSION_LIMIT = 250


@dataclass
class RunOutcome:
    investigation_id: str
    status: str
    report: Report | None
    markdown: str | None
    error: str | None = None


def _claim_rows(report: Report, notes: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(section: str, claim: Claim) -> None:
        rows.append(
            {
                "section": section,
                "text": claim.text,
                "numbers": [n.model_dump(mode="json") for n in claim.numbers],
                "evidence_ids": claim.evidence_ids,
                "status": claim.status,
                "checker_notes": notes.get(claim.text),
            }
        )

    for claim in report.summary:
        add("summary", claim)
    for claim in report.findings:
        add("findings", claim)
    for hypothesis in report.hypotheses:
        for claim in hypothesis.support:
            add("hypotheses", claim)
    for claim in report.unverified:
        add("unverified", claim)
    return rows


class Investigator:
    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        provider: LLMProvider,
        gateway: ToolGateway,
        prompts: PromptStore,
        bus: EventBus,
    ) -> None:
        self.settings = settings
        self.db = db
        self.provider = provider
        self.gateway = gateway
        self.prompts = prompts
        self.bus = bus
        self._tasks: set[asyncio.Task[RunOutcome]] = set()

    # ------------------------------------------------------------------ public interface

    async def run_investigation(
        self, question: str, scope: Scope | None = None, mode: str = "single"
    ) -> RunOutcome:
        """Create and run one investigation to completion (eval harness, tests, CLI)."""
        scope = scope or Scope()
        investigation_id = await self.create(question, scope, mode)
        return await self.execute(investigation_id, question, scope, mode)

    async def start(self, question: str, scope: Scope, mode: str) -> str:
        """Create an investigation and run it as a background task (the API path)."""
        investigation_id = await self.create(question, scope, mode)
        task = asyncio.create_task(self.execute(investigation_id, question, scope, mode))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return investigation_id

    async def create(self, question: str, scope: Scope, mode: str) -> str:
        investigation_id = str(uuid.uuid4())
        await self.db.create_investigation(
            investigation_id=investigation_id,
            question=question,
            scope=scope.model_dump(mode="json"),
            mode=mode,
            llm_model=self.provider.model_id,
            prompt_hashes=self.prompts.hashes(mode),
        )
        return investigation_id

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ one run

    async def execute(
        self, investigation_id: str, question: str, scope: Scope, mode: str
    ) -> RunOutcome:
        await self.db.set_status(investigation_id, "running")
        budget = Budget(
            max_tool_calls=self.settings.max_tool_calls,
            max_input_tokens=self.settings.max_input_tokens,
            max_seconds=self.settings.max_seconds,
        )
        ledger = Ledger(self.db, self.bus, investigation_id)
        ctx: RunContext | None = None
        try:
            specs = await self.gateway.list_tools()
            ctx = RunContext(
                investigation_id=investigation_id,
                question=question,
                scope=scope,
                mode=mode,
                provider=self.provider,
                gateway=self.gateway,
                prompts=self.prompts,
                ledger=ledger,
                budget=budget,
                tool_specs=specs,
                temperature=self.settings.llm_temperature,
            )
            graph = build_graph(ctx)
            try:
                async with asyncio.timeout(self.settings.max_seconds) as deadline:
                    final = await graph.ainvoke(
                        {"status": "running", "revisions": 0},
                        config={"recursion_limit": RECURSION_LIMIT},
                    )
            except TimeoutError:
                if not deadline.expired():
                    raise
                raise BudgetExceeded(
                    f"wall-time budget reached ({self.settings.max_seconds:g} s)"
                ) from None
            status = str(final["status"])
            report = Report.model_validate(final["report"])
        except BudgetExceeded as exc:
            if ctx is None:
                return await self._fail(investigation_id, ledger, budget, str(exc))
            budget.stop_reason = exc.reason
            await ledger.step("budget", "error", {"message": f"budget exceeded: {exc.reason}"})
            status = "budget_exceeded"
            report = build_report(ctx, {}, status)
        except asyncio.CancelledError:
            await self._fail(investigation_id, ledger, budget, "service shut down during the run")
            raise
        except Exception as exc:
            logger.exception("investigation failed", extra={"investigation_id": investigation_id})
            return await self._fail(
                investigation_id, ledger, budget, f"{type(exc).__name__}: {exc}"
            )
        return await self._finish(investigation_id, ledger, budget, ctx, status, report)

    async def _finish(
        self,
        investigation_id: str,
        ledger: Ledger,
        budget: Budget,
        ctx: RunContext,
        status: str,
        report: Report,
    ) -> RunOutcome:
        notes = {}
        if ctx.last_check is not None:
            notes = {r.claim.text: "; ".join(r.notes) for r in ctx.last_check.results if r.notes}
        await self.db.insert_claims(investigation_id, _claim_rows(report, notes))
        payload: dict[str, Any] = {"status": status}
        if status == "refused" and report.limitations:
            payload["reason"] = report.limitations[0]
        await ledger.step("reporter", "report", payload)
        report_json = report.model_dump(mode="json")
        await self.db.finish_investigation(
            investigation_id,
            status=status,
            report=report_json,
            tokens_in=budget.input_tokens,
            tokens_out=budget.output_tokens,
            cost_usd=0.0,
        )
        markdown = render_markdown(report, status=status, evidence=ledger.evidence)
        self.bus.publish(
            investigation_id,
            {
                "event": "report",
                "data": {"status": status, "report": report_json, "markdown": markdown},
            },
        )
        return RunOutcome(investigation_id, status, report, markdown)

    async def _fail(
        self, investigation_id: str, ledger: Ledger, budget: Budget, message: str
    ) -> RunOutcome:
        message = message[:500]
        try:
            await ledger.step("runner", "error", {"message": message})
            await self.db.finish_investigation(
                investigation_id,
                status="failed",
                report=None,
                tokens_in=budget.input_tokens,
                tokens_out=budget.output_tokens,
                cost_usd=0.0,
            )
        finally:
            self.bus.publish(
                investigation_id,
                {"event": "error", "data": {"status": "failed", "message": message}},
            )
        return RunOutcome(investigation_id, "failed", None, None, message)
