"""Orchestrated mode: planner, parallel workers with tool subsets (FR-AGT-3, FR-AGT-4)."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import psycopg
import pytest
from agent_support import (
    H1,
    QUESTION,
    RATES,
    afr_claim,
    draft,
    failures_claim,
    in_scope,
    make_investigator,
    ratio_claim,
)
from cohortex_agent.llm.base import LLMRequest, LLMResponse
from cohortex_agent.llm.scripted import ScriptedProvider, text, tool_calls
from cohortex_agent.schemas import Scope
from cohortex_agent.tools.fake import FakeToolGateway

pytestmark = pytest.mark.asyncio

PLAN = {
    "restated_question": "Did ST12000NM000J's AFR change from Q1 to Q2 2026?",
    "scope": {"source": "backblaze", "models": ["ST12000NM000J"], "date_from": "2026-01-01"},
    "tasks": [
        {"id": "t1", "kind": "data", "goal": "Quarterly AFR of ST12000NM000J, H1 2026."},
        {"id": "t2", "kind": "data", "goal": "Fleet summary for Backblaze, H1 2026."},
        {
            "id": "t3",
            "kind": "stats",
            "goal": "Compare Q2 vs Q1 failure rates using t1.",
            "depends_on": ["t1"],
        },
    ],
}
FLEET_ARGS = {"source": "backblaze", "from": "2026-01-01", "to": "2026-06-30"}


def task_id(request: LLMRequest) -> str:
    match = re.search(r'"id": "(t\d)"', str(request.messages[1]["content"]))
    assert match is not None
    return match.group(1)


class Workers:
    """Scripted workers that answer by task ID, so parallel order does not matter."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def respond(self, request: LLMRequest) -> LLMResponse:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.05)  # let the other workers of the superstep start
        self.active -= 1
        tid = task_id(request)
        turn = sum(1 for m in request.messages if m["role"] == "assistant")
        if tid == "t1":
            if turn == 0:  # also tries a stats tool it is not allowed to use
                return tool_calls(("fleet_cohort_afr", H1), ("stats_compare_rates", RATES))
            return text("t1-E1 has the AFR series; stats tools were not available.")
        if tid == "t2":
            if turn == 0:
                return tool_calls(("fleet_fleet_summary", FLEET_ARGS))
            return text("t2-E1 has the fleet totals.")
        assert "notes_from_dependencies" in str(request.messages[1]["content"])
        if turn == 0:
            return tool_calls(("stats_compare_rates", RATES))
        return text("t3-E1 has the rate ratio and p-value.")


class AsyncScripted(ScriptedProvider):
    def __init__(self, workers: Workers, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.workers = workers

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if request.node.startswith("worker:"):
            self.requests.append(request)
            return await self.workers.respond(request)
        return await super().complete(request)


def orchestrated_provider(planner: list[LLMResponse], drafts: int = 1) -> AsyncScripted:
    final = draft(
        summary=[afr_claim("t1-E1")],
        findings=[afr_claim("t1-E1"), failures_claim("t1-E1"), ratio_claim("t3-E1")],
    )
    return AsyncScripted(
        Workers(),
        script={
            "guard": [in_scope()],
            "planner": planner,
            "drafter": [text(final)] * drafts,
        },
    )


async def test_orchestrated_mode_completes(database_url: str) -> None:  # FR-AGT-3
    provider = orchestrated_provider([text(PLAN)])
    gateway = FakeToolGateway()
    outcome = await make_investigator(database_url, provider, gateway).run_investigation(
        QUESTION, Scope(), "orchestrated"
    )
    assert outcome.status == "completed", outcome.error
    report = outcome.report
    assert report is not None
    assert report.mode == "orchestrated"
    assert [c.status for c in report.findings] == ["supported"] * 3
    assert report.unverified == []
    # With no user scope, the report uses the planner's restated scope.
    assert report.scope.models == ["ST12000NM000J"]
    assert {"planner.v1", "worker.v1"} <= set(report.prompt_hashes)
    assert "agent.v1" not in report.prompt_hashes

    # t1 and t2 ran in the same superstep; t3 ran after t1.
    assert provider.workers.max_active == 2
    # Workers only reach their own tools: t1's stats call was refused and never executed.
    assert sorted((s, n) for s, n, _ in gateway.calls[:2]) == [
        ("fleet", "cohort_afr"),
        ("fleet", "fleet_summary"),
    ]
    assert [(s, n) for s, n, _ in gateway.calls[2:]] == [("stats", "compare_rates")]
    worker_tools = {
        tuple(sorted(t["function"]["name"] for t in r.tools or []))
        for r in provider.requests
        if r.node.startswith("worker:")
    }
    assert worker_tools == {
        tuple(
            sorted(
                [
                    "fleet_list_models",
                    "fleet_cohort_afr",
                    "fleet_compare_cohorts",
                    "fleet_fleet_summary",
                    "fleet_smart_trend",
                    "fleet_failed_drives",
                ]
            )
        ),
        ("stats_afr_ci", "stats_change_point", "stats_compare_rates"),
    }

    with psycopg.connect(database_url) as conn:
        steps = conn.execute(
            b"SELECT node, kind, payload FROM investigation_step WHERE investigation_id = %s"
            b" ORDER BY seq",
            (outcome.investigation_id,),
        ).fetchall()
        evidence_count = conn.execute(
            b"SELECT count(*) FROM evidence WHERE investigation_id = %s",
            (outcome.investigation_id,),
        ).fetchone()
    assert steps[0][:2] == ("planner", "plan")
    assert steps[0][2]["plan"]["tasks"][2]["depends_on"] == ["t1"]
    refused = [p for n, k, p in steps if k == "tool_call" and not p["ok"]]
    assert len(refused) == 1
    assert refused[0]["tool"] == "stats.compare_rates"
    assert refused[0]["summary"].startswith("error not_found")
    assert {n for n, k, _ in steps if k == "tool_call"} == {"worker:data", "worker:stats"}
    assert evidence_count == (4,)
    assert [k for _, k, _ in steps][-3:] == ["draft", "check", "report"]


async def test_malformed_plan_is_repaired_once(database_url: str) -> None:  # FR-AGT-4
    malformed = {**PLAN, "tasks": [{"id": "t1", "kind": "magic", "goal": "x"}]}
    provider = orchestrated_provider([text(malformed), text(PLAN)])
    outcome = await make_investigator(database_url, provider).run_investigation(
        QUESTION, mode="orchestrated"
    )
    assert outcome.status == "completed", outcome.error
    planner_calls = provider.calls_for("planner")
    assert len(planner_calls) == 2
    repair = planner_calls[1].messages
    assert repair[-2] == {"role": "assistant", "content": json.dumps(malformed)}
    assert "Validation errors" in repair[-1]["content"]
    assert "tasks.0.kind" in repair[-1]["content"]


async def test_cyclic_plan_counts_as_malformed(database_url: str) -> None:  # FR-AGT-4
    cyclic = {
        **PLAN,
        "tasks": [
            {"id": "t1", "kind": "data", "goal": "a", "depends_on": ["t2"]},
            {"id": "t2", "kind": "data", "goal": "b", "depends_on": ["t1"]},
        ],
    }
    provider = orchestrated_provider([text(cyclic), text("not json at all")])
    outcome = await make_investigator(database_url, provider).run_investigation(
        QUESTION, mode="orchestrated"
    )
    assert outcome.status == "failed"
    assert "cycle" in provider.calls_for("planner")[1].messages[-1]["content"]


async def test_plan_still_malformed_after_repair_fails_cleanly(database_url: str) -> None:
    """FR-AGT-4: after the single repair attempt the run fails with a clear error step."""
    provider = orchestrated_provider([text("{}"), text({"tasks": []})])
    gateway = FakeToolGateway()
    outcome = await make_investigator(database_url, provider, gateway).run_investigation(
        QUESTION, mode="orchestrated"
    )
    assert outcome.status == "failed"
    assert outcome.report is None
    assert outcome.error is not None
    assert "planner" in outcome.error
    assert len(provider.calls_for("planner")) == 2
    assert gateway.calls == []
    with psycopg.connect(database_url) as conn:
        status, report = conn.execute(
            b"SELECT status, report FROM investigation WHERE id = %s",
            (outcome.investigation_id,),
        ).fetchone() or (None, None)
        steps = conn.execute(
            b"SELECT kind, payload FROM investigation_step WHERE investigation_id = %s",
            (outcome.investigation_id,),
        ).fetchall()
    assert (status, report) == ("failed", None)
    assert [k for k, _ in steps] == ["error"]
    assert "structured output invalid after one repair" in steps[0][1]["message"]
    assert "Traceback" not in steps[0][1]["message"]
