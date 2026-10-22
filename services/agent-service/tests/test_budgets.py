"""Budget guards: tool calls, input tokens, wall time (FR-AGT-8)."""

from __future__ import annotations

import asyncio

import psycopg
import pytest
from agent_support import H1, QUESTION, afr_claim, draft, in_scope, make_investigator
from cohortex_agent.llm.base import LLMRequest, LLMResponse
from cohortex_agent.llm.scripted import ScriptedProvider, text, tool_calls
from cohortex_agent.schemas import Scope
from cohortex_agent.tools.fake import FakeToolGateway

pytestmark = pytest.mark.asyncio

SUMMARY_ARGS = {"source": "backblaze", "from": "2026-01-01", "to": "2026-06-30"}


def statuses(database_url: str, investigation_id: str) -> tuple[str, int]:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            b"SELECT i.status, (SELECT count(*) FROM evidence e WHERE e.investigation_id = i.id)"
            b" FROM investigation i WHERE i.id = %s",
            (investigation_id,),
        ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1])


async def test_tool_call_guard_stops_gathering_and_keeps_a_partial_report(
    database_url: str,
) -> None:
    provider = ScriptedProvider(
        {
            "guard": [in_scope()],
            "agent": [
                tool_calls(
                    ("fleet_cohort_afr", H1),
                    ("fleet_fleet_summary", SUMMARY_ARGS),
                    ("fleet_list_models", {"source": "backblaze"}),
                )
            ],
            "drafter": [text(draft(summary=[afr_claim()], findings=[afr_claim()]))],
        }
    )
    gateway = FakeToolGateway()
    outcome = await make_investigator(
        database_url, provider, gateway, max_tool_calls=2
    ).run_investigation(QUESTION, Scope(source="backblaze"))

    assert outcome.status == "budget_exceeded"
    assert len(gateway.calls) == 2  # the third call was never executed
    assert statuses(database_url, outcome.investigation_id) == ("budget_exceeded", 2)
    report = outcome.report
    assert report is not None
    assert [c.status for c in report.summary] == ["supported"]  # drafted from what was gathered
    assert any("tool-call budget reached (2 calls)" in x for x in report.limitations)


async def test_input_token_guard_stops_the_run(database_url: str) -> None:
    provider = ScriptedProvider(
        {
            "guard": [in_scope()],  # 100 input tokens
            "agent": [tool_calls(("fleet_cohort_afr", H1)), text("never reached")],  # +100
            "drafter": [text(draft(findings=[afr_claim()]))],
        }
    )
    outcome = await make_investigator(
        database_url, provider, max_input_tokens=150
    ).run_investigation(QUESTION)

    assert outcome.status == "budget_exceeded"
    assert [r.node for r in provider.requests] == ["guard", "agent"]
    assert outcome.report is not None
    assert outcome.report.findings == []
    assert any("input-token budget reached (200 of 150)" in x for x in outcome.report.limitations)
    assert statuses(database_url, outcome.investigation_id) == ("budget_exceeded", 1)


class SlowProvider(ScriptedProvider):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        if request.node == "agent" and len(self.calls_for("agent")) >= 1:
            await asyncio.sleep(5)
        return await super().complete(request)


async def test_wall_time_guard_stops_a_slow_run(database_url: str) -> None:
    provider = SlowProvider(
        {
            "guard": [in_scope()],
            "agent": [tool_calls(("fleet_cohort_afr", H1)), text("too late")],
            "drafter": [text(draft(findings=[afr_claim()]))],
        }
    )
    started = asyncio.get_running_loop().time()
    outcome = await make_investigator(database_url, provider, max_seconds=0.5).run_investigation(
        QUESTION
    )
    assert asyncio.get_running_loop().time() - started < 3
    assert outcome.status == "budget_exceeded"
    assert outcome.report is not None
    assert any("wall-time budget reached (0.5 s)" in x for x in outcome.report.limitations)
    assert statuses(database_url, outcome.investigation_id) == ("budget_exceeded", 1)
    with psycopg.connect(database_url) as conn:
        kinds = [
            r[0]
            for r in conn.execute(
                b"SELECT kind FROM investigation_step WHERE investigation_id = %s ORDER BY seq",
                (outcome.investigation_id,),
            )
        ]
    assert kinds == ["tool_call", "error", "report"]
