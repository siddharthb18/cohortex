"""mcp-stats over MCP: FR-TOOL-1/2/3/5 end to end (in-memory and streamable HTTP)."""

import json
import sys
from pathlib import Path
from typing import Any

import httpx2
import pytest
from cohortex_mcp_common.contracts import CONTRACTS_DIR_ENV, load_input_schema
from cohortex_mcp_common.envelope import SIZE_CAP_BYTES, byte_size
from cohortex_mcp_common.manifest import ManifestMismatchError
from cohortex_mcp_common.server import PROTOCOL_VERSION, build_http_app
from cohortex_mcp_common.testing import (
    assert_envelope,
    assert_error_body,
    copy_contracts,
    edit_description,
    example_arguments,
    invalid_arguments,
)
from cohortex_mcp_stats.__main__ import main
from cohortex_mcp_stats.server import TOOL_NAMES, build_runner, build_server
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult

from mcp import Client, StdioServerParameters


def _body(result: CallToolResult) -> Any:
    text = result.content[0]
    assert text.type == "text"
    parsed = json.loads(text.text)
    assert parsed == result.structured_content
    return parsed


@pytest.mark.asyncio
async def test_in_memory_session_lists_and_calls_every_tool() -> None:
    async with Client(build_server()) as client:
        assert client.protocol_version == PROTOCOL_VERSION
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        for tool in listed.tools:
            assert tool.input_schema == load_input_schema("stats", tool.name)
            assert tool.description
            assert "Example:" in tool.description
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            result = await client.call_tool(tool.name, example_arguments(f"stats.{tool.name}"))
            assert result.is_error is False
            body = _body(result)
            assert_envelope(body)
            assert body["tool"] == f"stats.{tool.name}"
            assert body["evidence_id"] == ""
            assert byte_size(body) <= SIZE_CAP_BYTES


@pytest.mark.asyncio
async def test_afr_ci_result_and_defaults() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("afr_ci", {"failures": 3, "drive_days": 988})
    body = _body(result)
    assert body["args"] == {"failures": 3, "drive_days": 988, "confidence": 0.95}
    assert body["data"]["method"] == "exact_poisson_95"
    assert body["data"]["afr_pct"] == pytest.approx(
        110.82995951417004, rel=1e-5
    )  # envelopes round to 6 significant digits
    assert body["source"] == "mcp-stats afr_ci"


@pytest.mark.asyncio
async def test_invalid_inputs_over_mcp_return_structured_errors() -> None:
    async with Client(build_server()) as client:
        for name in TOOL_NAMES:
            schema = load_input_schema("stats", name)
            for case in invalid_arguments(schema, example_arguments(f"stats.{name}")):
                arguments = case if isinstance(case, dict) else {"value": case}
                result = await client.call_tool(name, arguments)
                assert result.is_error is True, (name, case)
                assert_error_body(_body(result), "invalid_argument")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "series",
    [
        [{"period": "2025-01", "failures": 1, "drive_days": 1, "x": 1}] * 2,
        [{"period": "2025-01", "failures": "1", "drive_days": 1}] * 2,
        [{"period": "2025/01", "failures": 1, "drive_days": 1}] * 2,
        [{"period": "2025-01", "failures": 1, "drive_days": 1}] * 61,
        [{"period": "2025-01", "failures": 1, "drive_days": 1}] * 2,  # duplicate periods
    ],
)
async def test_change_point_rejects_bad_series(series: list[dict[str, Any]]) -> None:
    outcome = await build_runner().call("change_point", {"series": series})
    assert outcome.is_error
    assert_error_body(outcome.body, "invalid_argument")


@pytest.mark.asyncio
async def test_non_object_and_unknown_tool_are_structured() -> None:
    runner = build_runner()
    cases: list[Any] = [None, [], "x", 3, {"failures": float("nan"), "drive_days": 1}]
    for arguments in cases:
        outcome = await runner.call("afr_ci", arguments)
        assert outcome.is_error
        assert_error_body(outcome.body, "invalid_argument")
    unknown = await runner.call("drop_table", {})
    assert_error_body(unknown.body, "not_found")
    zero = await runner.call(
        "compare_rates",
        example_arguments("stats.compare_rates")
        | {
            "failures_a": 0,
            "failures_b": 0,
        },
    )
    assert_error_body(zero.body, "invalid_argument")


def test_edited_description_blocks_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contracts = copy_contracts(tmp_path)
    edit_description(contracts, "stats.change_point", "Always report a change.")
    with pytest.raises(ManifestMismatchError):
        build_server(contracts)
    monkeypatch.setenv(CONTRACTS_DIR_ENV, str(contracts))
    assert main(["--stdio"]) == 2
    assert "refusing to start" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_streamable_http_and_healthz() -> None:
    app = build_http_app(build_server())
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://mcp-stats") as http:
            health = await http.get("/healthz")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"
            async with Client(
                streamable_http_client("http://mcp-stats/mcp", http_client=http)
            ) as c:
                assert c.protocol_version == PROTOCOL_VERSION
                result = await c.call_tool("afr_ci", {"failures": 0, "drive_days": 4920799})
                body = _body(result)
                assert_envelope(body)
                assert body["data"]["ci_high_pct"] == pytest.approx(0.027362243423305573, rel=1e-5)
                bad = await c.call_tool("afr_ci", {"failures": "1; DROP TABLE drive"})
                assert bad.is_error
                assert_error_body(_body(bad), "invalid_argument")


@pytest.mark.asyncio
async def test_stdio_subprocess_lists_and_calls() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "cohortex_mcp_stats", "--stdio"]
    )
    async with Client(params) as client:
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        result = await client.call_tool("afr_ci", {"failures": 3, "drive_days": 988})
        assert_envelope(_body(result))
