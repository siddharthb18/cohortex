"""MCP adapter over the MCP Python SDK 2.x client (ADR-012), against in-process servers."""

from __future__ import annotations

import json
from typing import Any

import pytest
from cohortex_agent.tools.base import ToolCallError, compact_schema, split_llm_name
from cohortex_agent.tools.mcp_gateway import McpToolGateway
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

pytestmark = pytest.mark.asyncio


def fleet_server() -> MCPServer:
    server = MCPServer("cohortex-fleet-test")

    @server.tool(description="AFR series for one model (percent).")
    def cohort_afr(source: str, model: str) -> dict[str, Any]:
        return {
            "evidence_id": "",
            "tool": "fleet.cohort_afr",
            "args": {"source": source, "model": model},
            "source": "fleet-api /v1/cohorts/{source}/{model}/afr",
            "generated_at": "2026-10-02T16:20:11Z",
            "data": {"series": [{"period": "2026Q2", "failures": 9, "afr_pct": 3.3456}]},
            "truncated": False,
            "next_page": None,
        }

    @server.tool(description="Always fails with a structured error.")
    def broken(model: str) -> CallToolResult:
        body = {"error": {"code": "not_found", "message": f"unknown model {model}"}}
        return CallToolResult(content=[TextContent(text=json.dumps(body))], is_error=True)

    return server


def stats_server() -> MCPServer:
    server = MCPServer("cohortex-stats-test")

    @server.tool(description="AFR with a confidence interval.")
    def afr_ci(failures: int, drive_days: int) -> dict[str, Any]:
        return {"afr_pct": failures * 36500 / drive_days, "method": "exact_poisson_95"}

    return server


async def test_lists_tools_with_server_names_and_schemas() -> None:
    gateway = McpToolGateway({"fleet": fleet_server(), "stats": stats_server()})
    specs = await gateway.list_tools()
    assert [(s.server, s.name, s.llm_name, s.qualified_name) for s in specs] == [
        ("fleet", "cohort_afr", "fleet_cohort_afr", "fleet.cohort_afr"),
        ("fleet", "broken", "fleet_broken", "fleet.broken"),
        ("stats", "afr_ci", "stats_afr_ci", "stats.afr_ci"),
    ]
    afr = specs[0]
    assert afr.description == "AFR series for one model (percent)."
    assert set(afr.input_schema["required"]) == {"source", "model"}
    openai_spec = afr.to_openai()
    assert openai_spec["function"]["name"] == "fleet_cohort_afr"
    assert openai_spec["function"]["parameters"] == compact_schema(afr.input_schema)
    assert "title" not in json.dumps(openai_spec["function"]["parameters"])


async def test_call_returns_the_server_envelope() -> None:
    gateway = McpToolGateway({"fleet": fleet_server()})
    envelope = await gateway.call("fleet", "cohort_afr", {"source": "backblaze", "model": "X"})
    assert envelope["tool"] == "fleet.cohort_afr"
    assert envelope["evidence_id"] == ""  # the ledger fills it
    assert envelope["data"]["series"][0]["afr_pct"] == 3.3456
    assert envelope["truncated"] is False
    assert envelope["next_page"] is None


async def test_bare_data_is_wrapped_in_an_envelope() -> None:
    gateway = McpToolGateway({"stats": stats_server()})
    envelope = await gateway.call("stats", "afr_ci", {"failures": 9, "drive_days": 98189})
    assert envelope["tool"] == "stats.afr_ci"
    assert envelope["args"] == {"failures": 9, "drive_days": 98189}
    assert envelope["data"]["method"] == "exact_poisson_95"


async def test_tool_errors_become_typed_errors() -> None:
    gateway = McpToolGateway({"fleet": fleet_server()})
    with pytest.raises(ToolCallError) as info:
        await gateway.call("fleet", "broken", {"model": "X"})
    assert (info.value.code, info.value.message) == ("not_found", "unknown model X")
    with pytest.raises(ToolCallError) as missing:
        await gateway.call("fleet", "cohort_afr", {"source": "backblaze"})
    assert missing.value.code in {"invalid_argument", "upstream_error"}
    with pytest.raises(ToolCallError) as unknown_server:
        await gateway.call("docs", "search", {"query": "x"})
    assert unknown_server.value.code == "not_found"


async def test_unreachable_server_is_skipped_in_listings() -> None:
    gateway = McpToolGateway(
        {"fleet": fleet_server(), "stats": "http://127.0.0.1:9/mcp"}, timeout_seconds=2
    )
    specs = await gateway.list_tools()
    assert {s.server for s in specs} == {"fleet"}
    with pytest.raises(ToolCallError) as info:
        await gateway.call("stats", "afr_ci", {"failures": 1, "drive_days": 10})
    assert info.value.code == "upstream_error"


async def test_llm_names_split_on_the_first_underscore() -> None:
    assert split_llm_name("fleet_cohort_afr") == ("fleet", "cohort_afr")
    assert split_llm_name("docs_get_passage") == ("docs", "get_passage")
    for bad in ("cohort_afr", "fleet", "web_search_x", "fleet_"):
        with pytest.raises(ValueError, match="unknown tool"):
            split_llm_name(bad)
