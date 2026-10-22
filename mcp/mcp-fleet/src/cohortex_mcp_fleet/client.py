"""Typed async client for fleet-api (contracts §4, implementation-notes §5).

mcp-fleet never touches the database (ADR-002); every tool is one or more GETs through this client.
Failures become :class:`FleetApiError` with an implementation-notes §6 error code:

=========================  ==================
fleet-api answer           code
=========================  ==================
400 / 422 problem details  ``invalid_argument``
404                        ``not_found``
413                        ``too_large``
other status, bad JSON,    ``upstream_error``
unexpected shape, timeout,
connection failure
=========================  ==================
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from cohortex_mcp_common.errors import ErrorCode, clean_message
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

FLEET_API_URL_ENV = "FLEET_API_URL"
DEFAULT_FLEET_API_URL = "http://localhost:8080"
DEFAULT_TIMEOUT_S = 10.0
MAX_PAGE_SIZE = 500
"""fleet-api's largest page size (FR-API-8)."""

_DETAIL_CHARS = 200


class FleetApiError(Exception):
    """A fleet-api call failed; ``code`` is the structured tool error code."""

    def __init__(self, code: ErrorCode, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = clean_message(message)
        self.status = status


class _Open(BaseModel):
    """Response models keep fields they do not declare (passed through as evidence)."""

    model_config = ConfigDict(extra="allow")


class Paged[RowT: BaseModel](_Open):
    """``{"items": [...], "page", "size", "total"}`` (implementation-notes §5)."""

    items: list[RowT]
    page: int
    size: int
    total: int


class ModelRow(_Open):
    """One ``GET /v1/models`` row."""

    model: str
    media: str
    capacity_bytes: int | None = None
    drive_count: int


class AfrPoint(_Open):
    """One AFR series row."""

    period: str
    drive_days: int
    failures: int
    afr_pct: float
    ci_low_pct: float
    ci_high_pct: float


class AfrSeries(_Open):
    """``GET /v1/cohorts/{source}/{model}/afr``."""

    series: list[AfrPoint]


class CompareRow(_Open):
    """One ranked cohort of ``GET /v1/cohorts/compare``."""

    model: str
    drive_days: int
    failures: int
    afr_pct: float
    ci_low_pct: float
    ci_high_pct: float
    rate_ratio_vs_fleet: float | None = None


class CompareResult(_Open):
    """``GET /v1/cohorts/compare``: fleet-api's ``cohorts`` object, an ``items`` object, or a bare
    JSON array of rows."""

    items: list[CompareRow]

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, value: Any) -> Any:
        if isinstance(value, list):
            return {"items": value}
        if isinstance(value, dict) and "items" not in value and "cohorts" in value:
            return {**value, "items": value["cohorts"]}
        return value


class FleetSummary(_Open):
    """``GET /v1/fleet/summary``."""

    drives: int
    drive_days: int
    failures: int
    afr_pct: float
    ci_low_pct: float
    ci_high_pct: float


class SmartPoint(_Open):
    """One SMART trend row (sampled drives only)."""

    period: str
    p50: float | None = None
    p95: float | None = None
    nonzero_share: float | None = None
    n_drives: int


class SmartTrend(_Open):
    """``GET /v1/cohorts/{source}/{model}/smart-trend``."""

    series: list[SmartPoint]


class FailedDrive(_Open):
    """One ``GET /v1/cohorts/{source}/{model}/failed-drives`` row."""

    drive_id: str
    failed_on: str
    age_days: int
    last_smart: dict[str, float | None]


def _cohort_path(source: str, model: str, leaf: str) -> str:
    return f"/v1/cohorts/{quote(source, safe='')}/{quote(model, safe='')}/{leaf}"


def _problem_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    text = body.get("detail") or body.get("title") or ""
    return clean_message(str(text))[:_DETAIL_CHARS]


class FleetApiClient:
    """Async fleet-api client. Inject ``http_client`` (e.g. with ``httpx.MockTransport``) in tests.

    Without one, a client is created for ``base_url``, else ``$FLEET_API_URL``, else
    ``http://localhost:8080``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if http_client is None:
            url = base_url or os.environ.get(FLEET_API_URL_ENV) or DEFAULT_FLEET_API_URL
            http_client = httpx.AsyncClient(base_url=url, timeout=timeout_s)
        self._http = http_client

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    async def get_json(self, path: str, params: dict[str, str | int]) -> Any:
        """GET ``path`` and return parsed JSON, mapping every failure to :class:`FleetApiError`."""
        try:
            response = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise FleetApiError("upstream_error", "fleet-api timed out") from exc
        except httpx.HTTPError as exc:
            raise FleetApiError("upstream_error", "fleet-api is unreachable") from exc
        status = response.status_code
        if status >= 400:
            detail = _problem_detail(response)
            suffix = f": {detail}" if detail else ""
            if status in (400, 422):
                raise FleetApiError(
                    "invalid_argument", f"fleet-api rejected the request{suffix}", status
                )
            if status == 404:
                raise FleetApiError(
                    "not_found", f"fleet-api found no such resource{suffix}", status
                )
            if status == 413:
                raise FleetApiError("too_large", f"fleet-api result too large{suffix}", status)
            raise FleetApiError("upstream_error", f"fleet-api returned HTTP {status}", status)
        try:
            return response.json()
        except ValueError as exc:
            raise FleetApiError(
                "upstream_error", "fleet-api returned invalid JSON", status
            ) from exc

    async def _get[ModelT: BaseModel](
        self, model: type[ModelT], path: str, params: dict[str, str | int]
    ) -> ModelT:
        body = await self.get_json(path, params)
        try:
            return model.model_validate(body)
        except ValidationError as exc:
            raise FleetApiError(
                "upstream_error",
                f"fleet-api response for {path.split('?')[0]} has an unexpected shape",
            ) from exc

    async def list_models(
        self, source: str, media: str | None, page: int, size: int = MAX_PAGE_SIZE
    ) -> Paged[ModelRow]:
        """``GET /v1/models``."""
        params: dict[str, str | int] = {"source": source, "page": page, "size": size}
        if media is not None:
            params["media"] = media
        return await self._get(Paged[ModelRow], "/v1/models", params)

    async def cohort_afr(
        self, source: str, model: str, date_from: str, date_to: str, granularity: str
    ) -> AfrSeries:
        """``GET /v1/cohorts/{source}/{model}/afr``."""
        params: dict[str, str | int] = {
            "from": date_from,
            "to": date_to,
            "granularity": granularity,
        }
        return await self._get(AfrSeries, _cohort_path(source, model, "afr"), params)

    async def compare(
        self, source: str, date_from: str, date_to: str, min_drives: int, limit: int
    ) -> CompareResult:
        """``GET /v1/cohorts/compare``."""
        params: dict[str, str | int] = {
            "source": source,
            "from": date_from,
            "to": date_to,
            "min_drives": min_drives,
            "limit": limit,
        }
        return await self._get(CompareResult, "/v1/cohorts/compare", params)

    async def fleet_summary(self, source: str, date_from: str, date_to: str) -> FleetSummary:
        """``GET /v1/fleet/summary``."""
        params: dict[str, str | int] = {"source": source, "from": date_from, "to": date_to}
        return await self._get(FleetSummary, "/v1/fleet/summary", params)

    async def smart_trend(
        self, source: str, model: str, attr: int, date_from: str, date_to: str, granularity: str
    ) -> SmartTrend:
        """``GET /v1/cohorts/{source}/{model}/smart-trend``."""
        params: dict[str, str | int] = {
            "attr": attr,
            "from": date_from,
            "to": date_to,
            "granularity": granularity,
        }
        return await self._get(SmartTrend, _cohort_path(source, model, "smart-trend"), params)

    async def failed_drives(
        self, source: str, model: str, date_from: str, date_to: str, page: int, size: int
    ) -> Paged[FailedDrive]:
        """``GET /v1/cohorts/{source}/{model}/failed-drives``."""
        params: dict[str, str | int] = {
            "from": date_from,
            "to": date_to,
            "page": page,
            "size": size,
        }
        return await self._get(
            Paged[FailedDrive], _cohort_path(source, model, "failed-drives"), params
        )
