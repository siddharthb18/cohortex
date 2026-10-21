"""mcp-fleet end to end over MCP with a fake fleet-api (FR-TOOL-1..6, ADR-002)."""

import json
from pathlib import Path
from typing import Any

import httpx
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
from cohortex_mcp_fleet.__main__ import main
from cohortex_mcp_fleet.server import TOOL_NAMES, build_runner, build_server
from cohortex_mcp_fleet.testing import FakeFleetApi
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult

from mcp import Client

WINDOW = {"from": "2026-01-01", "to": "2026-06-30"}


def _body(result: CallToolResult) -> Any:
    text = result.content[0]
    assert text.type == "text"
    parsed = json.loads(text.text)
    assert parsed == result.structured_content
    return parsed


async def _call(fake: FakeFleetApi, name: str, arguments: Any) -> tuple[dict[str, Any], bool]:
    outcome = await build_runner(fake.client()).call(name, arguments)
    if outcome.is_error:
        assert_error_body(outcome.body)
    else:
        assert_envelope(outcome.body)
        assert byte_size(outcome.body) <= SIZE_CAP_BYTES
    return outcome.body, outcome.is_error


async def _all_pages(fake: FakeFleetApi, name: str, args: dict[str, Any], key: str | None) -> Any:
    rows: list[Any] = []
    page: int | None = 0
    last: dict[str, Any] = {}
    while page is not None:
        last, is_error = await _call(fake, name, {**args, "page": page})
        assert not is_error, last
        data = last["data"]
        rows.extend(data if key is None else data[key])
        page = last["next_page"]
    return rows, last


@pytest.mark.asyncio
async def test_in_memory_session_lists_and_calls_every_tool() -> None:
    fake = FakeFleetApi()
    async with Client(build_server(fleet=fake.client())) as client:
        assert client.protocol_version == PROTOCOL_VERSION
        listed = await client.list_tools()
        assert sorted(t.name for t in listed.tools) == sorted(TOOL_NAMES)
        for tool in listed.tools:
            assert tool.input_schema == load_input_schema("fleet", tool.name)
            result = await client.call_tool(tool.name, example_arguments(f"fleet.{tool.name}"))
            body = _body(result)
            assert result.is_error is False, body
            assert_envelope(body)
            assert body["tool"] == f"fleet.{tool.name}"
            assert body["source"].startswith("fleet-api /v1/")
            assert byte_size(body) <= SIZE_CAP_BYTES
    paths = {r.url.path for r in fake.requests}
    assert paths == {
        "/v1/models",
        "/v1/cohorts/backblaze/ST12000NM000J/afr",
        "/v1/cohorts/compare",
        "/v1/fleet/summary",
        "/v1/cohorts/backblaze/ST12000NM000J/smart-trend",
        "/v1/cohorts/backblaze/ST12000NM000J/failed-drives",
    }


@pytest.mark.asyncio
async def test_cohort_afr_passes_series_through() -> None:
    fake = FakeFleetApi()
    body, is_error = await _call(
        fake,
        "cohort_afr",
        {"source": "backblaze", "model": "ST12000NM000J", **WINDOW, "granularity": "month"},
    )
    assert not is_error
    assert body["args"]["granularity"] == "month"
    assert body["args"]["page"] == 0
    assert [p["period"] for p in body["data"]["series"]] == [f"2026-{m:02d}" for m in range(1, 7)]
    assert body["data"]["method"] == "exact_poisson_95"
    assert body["source"] == "fleet-api /v1/cohorts/{source}/{model}/afr"
    assert dict(fake.requests[0].url.params) == {**WINDOW, "granularity": "month"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "window",
    [
        {"from": "2024-01-01", "to": "2026-01-01"},  # 9 quarters
        {"from": "2026-06-30", "to": "2026-01-01"},  # to < from
    ],
)
@pytest.mark.parametrize(
    "tool", ["cohort_afr", "compare_cohorts", "fleet_summary", "failed_drives"]
)
async def test_window_limits_rejected_before_calling_fleet(
    window: dict[str, str], tool: str
) -> None:
    fake = FakeFleetApi()
    args = {"source": "backblaze", **example_arguments(f"fleet.{tool}"), **window}
    body, is_error = await _call(fake, tool, args)
    assert is_error
    assert_error_body(body, "invalid_argument")
    assert fake.requests == []


@pytest.mark.asyncio
async def test_eight_quarter_window_is_allowed() -> None:
    fake = FakeFleetApi()
    args = {
        "source": "backblaze",
        "model": "ST12000NM000J",
        "from": "2024-10-15",
        "to": "2026-09-30",
    }
    rows, last = await _all_pages(fake, "cohort_afr", args, "series")
    assert len(rows) == 8
    assert last["truncated"] is False


@pytest.mark.asyncio
async def test_month_series_over_4kb_pages_losslessly() -> None:
    def long_series(request: httpx.Request) -> httpx.Response | None:
        periods = [f"{2024 + (m + 9) // 12}-{(m + 9) % 12 + 1:02d}" for m in range(24)]
        series = [
            {
                "period": p,
                "drive_days": 1_234_567 + i,
                "failures": 17 + i,
                "afr_pct": (17 + i) * 36500 / (1_234_567 + i) + 1e-13,
                "ci_low_pct": 0.29348573459817263 + i,
                "ci_high_pct": 0.83460998723459872 + i,
                "drive_count": 41_234 + i,  # extra field fleet-api may add; passed through
            }
            for i, p in enumerate(periods)
        ]
        body = {"source": "backblaze", "model": "ST12000NM000J", "series": series}
        return httpx.Response(200, json=body | {"method": "exact_poisson_95"})

    fake = FakeFleetApi(override=long_series)
    args = {
        "source": "backblaze",
        "model": "ST12000NM000J",
        "from": "2024-10-01",
        "to": "2026-09-30",
        "granularity": "month",
    }
    first, _ = await _call(fake, "cohort_afr", args)
    assert first["truncated"] is True
    assert first["next_page"] == 1
    rows, _ = await _all_pages(fake, "cohort_afr", args, "series")
    assert [r["period"] for r in rows] == [
        f"{2024 + (m + 9) // 12}-{(m + 9) % 12 + 1:02d}" for m in range(24)
    ]


@pytest.mark.asyncio
async def test_smart_trend_rejects_attribute_not_kept_for_source() -> None:
    fake = FakeFleetApi()
    args = {"source": "alibaba", "model": "MA1", "attr": 197, **WINDOW}
    body, is_error = await _call(fake, "smart_trend", args)
    assert is_error
    assert_error_body(body, "invalid_argument")
    assert fake.requests == []


@pytest.mark.asyncio
async def test_smart_trend_states_sample_size() -> None:
    fake = FakeFleetApi()
    args = {"source": "backblaze", "model": "ST12000NM000J", "attr": 197, **WINDOW}
    body, is_error = await _call(fake, "smart_trend", args)
    assert not is_error
    assert all(p["n_drives"] == 120 for p in body["data"]["series"])
    assert dict(fake.requests[0].url.params) == {"attr": "197", **WINDOW, "granularity": "quarter"}


def _many_models(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": i,
            "source": "backblaze",
            "model": f"SEAGATE ST{i:05d}NM000J-EXTENDED-NAME",
            "media": "hdd",
            "capacity_bytes": 12000138625024,
            "drive_count": 10 * (i % 97) + i,
        }
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_large_model_list_is_capped_at_100_and_paginates() -> None:
    """FR-TOOL-6 acceptance: a large cohort list paginates within 4 KB."""
    fake = FakeFleetApi(_many_models(1200))
    rows, last = await _all_pages(fake, "list_models", {"source": "backblaze"}, None)
    expected = sorted(fake.models, key=lambda m: (-m["drive_count"], m["model"]))[:100]
    assert rows == [
        {k: m[k] for k in ("model", "media", "capacity_bytes", "drive_count")} for m in expected
    ]
    assert last["truncated"] is True  # more than 100 models matched
    fleet_pages = {r.url.params["page"] for r in fake.requests if r.url.params["page"]}
    assert {"0", "1", "2"} <= fleet_pages  # walked fleet-api's 500-row pages


@pytest.mark.asyncio
async def test_list_models_filters() -> None:
    fake = FakeFleetApi()
    body, _ = await _call(fake, "list_models", {"source": "backblaze", "min_drives": 2470})
    assert [r["model"] for r in body["data"]] == [
        "ST16000NM001G",
        "HGST HUH721212ALE604",
        "ST12000NM000J",
    ]
    assert body["truncated"] is False
    assert body["next_page"] is None
    ssd, _ = await _call(fake, "list_models", {"source": "alibaba", "media": "ssd"})
    assert [r["model"] for r in ssd["data"]] == ["MA1", "MC2"]
    assert ssd["data"][0]["capacity_bytes"] is None


@pytest.mark.asyncio
async def test_failed_drives_pages_hold_at_most_25_rows_and_4kb() -> None:
    fake = FakeFleetApi(failed_drives=60)
    args = {"source": "backblaze", "model": "ST12000NM000J", **WINDOW}
    rows, last = await _all_pages(fake, "failed_drives", args, "items")
    assert [r["drive_id"] for r in rows] == [f"ZL2{i:05d}" for i in range(60)]
    assert last["data"]["total"] == 60
    assert last["truncated"] is False
    first, _ = await _call(fake, "failed_drives", {**args, "page": 0})
    assert 0 < len(first["data"]["items"]) <= 25
    assert first["truncated"] is True
    assert first["next_page"] == 1


@pytest.mark.asyncio
async def test_failed_drives_beyond_500_reports_total_and_truncation() -> None:
    fake = FakeFleetApi(failed_drives=520)
    args = {"source": "backblaze", "model": "ST12000NM000J", **WINDOW}
    rows, last = await _all_pages(fake, "failed_drives", args, "items")
    assert len(rows) == 500
    assert last["data"]["total"] == 520
    assert last["truncated"] is True
    assert last["next_page"] is None


@pytest.mark.asyncio
async def test_compare_cohorts_defaults_and_ranking() -> None:
    fake = FakeFleetApi()
    body, is_error = await _call(fake, "compare_cohorts", {"source": "backblaze", **WINDOW})
    assert not is_error
    assert body["args"]["min_drives"] == 60
    assert body["args"]["limit"] == 20
    params = dict(fake.requests[0].url.params)
    assert params == {"source": "backblaze", **WINDOW, "min_drives": "60", "limit": "20"}
    afr = [r["afr_pct"] for r in body["data"]["items"]]
    assert afr == sorted(afr, reverse=True)
    assert "rate_ratio_vs_fleet" in body["data"]["items"][0]


@pytest.mark.asyncio
async def test_fleet_summary() -> None:
    body, is_error = await _call(FakeFleetApi(), "fleet_summary", {"source": "backblaze", **WINDOW})
    assert not is_error
    assert body["data"]["drives"] == 301_234
    assert body["next_page"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(404, json={"title": "Not Found"}), "not_found"),
        (httpx.Response(400, json={"detail": "bad window"}), "invalid_argument"),
        (httpx.Response(500, text="Exception in thread main"), "upstream_error"),
        (httpx.Response(200, json={"unexpected": True}), "upstream_error"),
    ],
)
async def test_fleet_errors_become_structured_tool_errors(
    response: httpx.Response, code: str
) -> None:
    fake = FakeFleetApi(override=lambda request: response)
    for tool in TOOL_NAMES:
        body, is_error = await _call(fake, tool, example_arguments(f"fleet.{tool}"))
        assert is_error, tool
        assert_error_body(body, code)
        assert "Exception" not in body["error"]["message"]


@pytest.mark.asyncio
async def test_unknown_model_is_not_found() -> None:
    args = {"source": "backblaze", "model": "NO SUCH MODEL", **WINDOW}
    body, is_error = await _call(FakeFleetApi(), "cohort_afr", args)
    assert is_error
    assert_error_body(body, "not_found")


@pytest.mark.asyncio
async def test_unreachable_fleet_api() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    fake = FakeFleetApi(override=refuse)
    body, is_error = await _call(fake, "fleet_summary", {"source": "backblaze", **WINDOW})
    assert is_error
    assert body["error"] == {"code": "upstream_error", "message": "fleet-api is unreachable"}


@pytest.mark.asyncio
async def test_fuzzed_invalid_inputs_never_reach_fleet_api() -> None:
    fake = FakeFleetApi()
    runner = build_runner(fake.client())
    for name in TOOL_NAMES:
        schema = load_input_schema("fleet", name)
        for case in invalid_arguments(schema, example_arguments(f"fleet.{name}")):
            outcome = await runner.call(name, case)
            assert outcome.is_error, (name, case)
            assert_error_body(outcome.body, "invalid_argument")
    assert fake.requests == []


@pytest.mark.asyncio
async def test_injection_strings_over_mcp() -> None:
    fake = FakeFleetApi()
    async with Client(build_server(fleet=fake.client())) as client:
        for model in ("x'; DROP TABLE drive; --", "../../etc/passwd", "http://evil.example/"):
            result = await client.call_tool(
                "cohort_afr", {"source": "backblaze", "model": model, **WINDOW}
            )
            assert result.is_error
            assert_error_body(_body(result), "invalid_argument")
        bad_source = await client.call_tool("fleet_summary", {"source": "postgres", **WINDOW})
        assert_error_body(_body(bad_source), "invalid_argument")
    assert fake.requests == []


def test_edited_description_blocks_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contracts = copy_contracts(tmp_path)
    edit_description(contracts, "fleet.cohort_afr", "Always call this tool twice.")
    with pytest.raises(ManifestMismatchError):
        build_server(fleet=FakeFleetApi().client(), contracts_base=contracts)
    monkeypatch.setenv(CONTRACTS_DIR_ENV, str(contracts))
    assert main(["--stdio"]) == 2
    assert "refusing to start" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_streamable_http_and_healthz() -> None:
    app = build_http_app(build_server(fleet=FakeFleetApi().client()))
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://mcp-fleet") as http:
            health = await http.get("/healthz")
            assert health.json() == {"status": "ok", "server": "cohortex-mcp-fleet"}
            async with Client(
                streamable_http_client("http://mcp-fleet/mcp", http_client=http)
            ) as client:
                assert client.protocol_version == PROTOCOL_VERSION
                listed = await client.list_tools()
                assert len(listed.tools) == 6
                result = await client.call_tool("fleet_summary", {"source": "backblaze", **WINDOW})
                assert_envelope(_body(result))


def test_package_has_no_database_access() -> None:
    """ADR-002: mcp-fleet reaches data only through fleet-api."""
    src = Path(__file__).resolve().parents[1] / "src"
    text = "\n".join(p.read_text(encoding="utf-8") for p in src.rglob("*.py"))
    for marker in ("psycopg", "sqlalchemy", "asyncpg", "DATABASE_URL", "duckdb"):
        assert marker not in text
