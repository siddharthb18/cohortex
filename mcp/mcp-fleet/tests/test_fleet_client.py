"""FleetApiClient: request shapes, response parsing, problem-details mapping (ADR-002)."""

from collections.abc import Callable

import httpx
import pytest
from cohortex_mcp_fleet.client import (
    DEFAULT_FLEET_API_URL,
    FLEET_API_URL_ENV,
    FleetApiClient,
    FleetApiError,
)
from cohortex_mcp_fleet.testing import FakeFleetApi


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> FleetApiClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://fleet")
    return FleetApiClient(http_client=http)


@pytest.mark.asyncio
async def test_list_models_sends_paging_params() -> None:
    fake = FakeFleetApi()
    page = await fake.client().list_models("backblaze", "hdd", page=0)
    assert page.total == 4
    assert page.items[0].model == "ST12000NM000J"
    params = fake.requests[0].url.params
    assert dict(params) == {"source": "backblaze", "page": "0", "size": "500", "media": "hdd"}


@pytest.mark.asyncio
async def test_model_with_space_is_path_encoded() -> None:
    fake = FakeFleetApi()
    afr = await fake.client().cohort_afr(
        "backblaze", "HGST HUH721212ALE604", "2026-01-01", "2026-06-30", "quarter"
    )
    assert [p.period for p in afr.series] == ["2026Q1", "2026Q2"]
    raw = fake.requests[0].url.raw_path.decode()
    assert raw.startswith("/v1/cohorts/backblaze/HGST%20HUH721212ALE604/afr?")
    assert afr.model_dump()["method"] == "exact_poisson_95"  # extra fields are kept


@pytest.mark.asyncio
async def test_compare_accepts_bare_list() -> None:
    row = {
        "model": "M",
        "drive_days": 10,
        "failures": 1,
        "afr_pct": 3650.0,
        "ci_low_pct": 1.0,
        "ci_high_pct": 9999.0,
        "rate_ratio_vs_fleet": 2.0,
    }
    client = _client(lambda request: httpx.Response(200, json=[row]))
    result = await client.compare("backblaze", "2026-01-01", "2026-03-31", 60, 20)
    assert result.items[0].model == "M"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(400, json={"detail": "too long"}), "invalid_argument"),
        (httpx.Response(422, json={"title": "Unprocessable"}), "invalid_argument"),
        (httpx.Response(404, json={"title": "Not Found", "detail": "no model X"}), "not_found"),
        (httpx.Response(413, text="too big"), "too_large"),
        (httpx.Response(500, text="java.lang.NullPointerException at ..."), "upstream_error"),
        (httpx.Response(503), "upstream_error"),
        (httpx.Response(200, text="<html>"), "upstream_error"),
        (httpx.Response(200, json={"series": [{"period": "2026Q1"}]}), "upstream_error"),
    ],
)  # fmt: skip
async def test_failures_map_to_error_codes(response: httpx.Response, code: str) -> None:
    client = _client(lambda request: response)
    with pytest.raises(FleetApiError) as info:
        await client.cohort_afr("backblaze", "M", "2026-01-01", "2026-03-31", "quarter")
    assert info.value.code == code
    assert "NullPointerException" not in info.value.message
    assert "Traceback" not in info.value.message


@pytest.mark.asyncio
async def test_problem_detail_is_included() -> None:
    client = _client(lambda r: httpx.Response(400, json={"detail": "window\nspans 9 quarters"}))
    with pytest.raises(FleetApiError) as info:
        await client.fleet_summary("backblaze", "2024-01-01", "2026-03-31")
    assert info.value.message == "fleet-api rejected the request: window spans 9 quarters"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (httpx.ConnectError("refused http://10.0.0.5:8080"), "fleet-api is unreachable"),
        (httpx.ReadTimeout("read timed out"), "fleet-api timed out"),
    ],
)  # fmt: skip
async def test_network_errors_are_generic(exc: Exception, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    with pytest.raises(FleetApiError) as info:
        await _client(handler).fleet_summary("backblaze", "2026-01-01", "2026-03-31")
    assert info.value.code == "upstream_error"
    assert info.value.message == message


@pytest.mark.asyncio
async def test_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FLEET_API_URL_ENV, raising=False)
    default = FleetApiClient()
    assert str(default._http.base_url).rstrip("/") == DEFAULT_FLEET_API_URL
    await default.aclose()
    monkeypatch.setenv(FLEET_API_URL_ENV, "http://fleet-api:8080")
    configured = FleetApiClient()
    assert str(configured._http.base_url).rstrip("/") == "http://fleet-api:8080"
    await configured.aclose()
