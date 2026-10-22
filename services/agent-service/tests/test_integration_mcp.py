"""Integration: the agent talks to the real mcp-fleet and mcp-stats servers (in-memory MCP sessions).

mcp-fleet is backed by its contract-shaped fake fleet-api; mcp-stats is the real implementation, so
a claim citing its rate ratio must pass the code checker end to end (FR-AGT-5/6, FR-TOOL-3).
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_support import H1, QUESTION, RATES, claim, draft, in_scope, make_investigator, ref
from cohortex_agent.llm.scripted import ScriptedProvider, text, tool_calls
from cohortex_agent.schemas import Scope
from cohortex_agent.tools.mcp_gateway import McpToolGateway
from cohortex_mcp_fleet.server import build_server as build_fleet
from cohortex_mcp_fleet.testing import FakeFleetApi
from cohortex_mcp_stats.server import build_server as build_stats
from cohortex_mcp_stats.stats import compare_rates

pytestmark = pytest.mark.asyncio


async def test_single_mode_against_real_mcp_servers(database_url: str) -> None:
    expected: dict[str, Any] = compare_rates(**RATES)
    good = claim(
        "The Q2/Q1 rate ratio was computed by the stats tool.",
        [ref(round(expected["rate_ratio"], 4), "ratio", "E2", "rate_ratio")],
        ["E2"],
    )
    fabricated = claim(
        "The Q2/Q1 rate ratio was 9.99.", [ref(9.99, "ratio", "E2", "rate_ratio")], ["E2"]
    )
    provider = ScriptedProvider(
        {
            "guard": [in_scope()],
            "agent": [
                tool_calls(("fleet_cohort_afr", H1)),
                tool_calls(("stats_compare_rates", RATES)),
                text("E2 holds the rate ratio."),
            ],
            "drafter": [text(draft(summary=[good], findings=[good, fabricated]))] * 3,
        }
    )
    gateway = McpToolGateway(
        {"fleet": build_fleet(fleet=FakeFleetApi().client()), "stats": build_stats()}
    )
    names = {f"{t.server}_{t.name}" for t in await gateway.list_tools()}
    assert {"fleet_cohort_afr", "stats_compare_rates", "stats_afr_ci"} <= names

    outcome = await make_investigator(database_url, provider, gateway).run_investigation(
        QUESTION, Scope(source="backblaze"), "single"
    )

    assert outcome.status == "completed", outcome.error
    report = outcome.report
    assert report is not None
    assert [c.status for c in report.summary] == ["supported"]
    assert [c.text for c in report.unverified] == [fabricated["text"]]
