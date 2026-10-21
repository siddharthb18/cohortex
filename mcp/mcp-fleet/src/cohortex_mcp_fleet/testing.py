"""A fake fleet-api for tests (here and in agent-service), served through ``httpx.MockTransport``.

Responses follow contracts §4 and implementation-notes §5: paged lists are
``{items, page, size, total}``, AFR responses carry ``method`` and ``generated_at``, errors are
RFC 9457 problem details. Numbers are synthetic; they illustrate shapes, not fleet truth.

Usage::

    fake = FakeFleetApi()
    server = build_server(fleet=fake.client())
    async with mcp.Client(server) as client:
        await client.call_tool("cohort_afr", {...})
    fake.requests  # what mcp-fleet asked fleet-api
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import unquote

import httpx

from cohortex_mcp_fleet.client import FleetApiClient

GENERATED_AT = "2026-10-02T16:20:11Z"
METHOD = "exact_poisson_95"
HDD_ATTRS = (5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242)

DEFAULT_MODELS: tuple[dict[str, Any], ...] = (
    {"id": 1, "source": "backblaze", "model": "ST12000NM000J", "media": "hdd",
     "capacity_bytes": 12000138625024, "drive_count": 2470},
    {"id": 2, "source": "backblaze", "model": "HGST HUH721212ALE604", "media": "hdd",
     "capacity_bytes": 12000138625024, "drive_count": 13105},
    {"id": 3, "source": "backblaze", "model": "ST16000NM001G", "media": "hdd",
     "capacity_bytes": 16000900661248, "drive_count": 35012},
    {"id": 4, "source": "backblaze", "model": "WDC WUH722222ALE6L4", "media": "hdd",
     "capacity_bytes": 22000969973760, "drive_count": 41},
    {"id": 5, "source": "alibaba", "model": "MA1", "media": "ssd",
     "capacity_bytes": None, "drive_count": 98000},
    {"id": 6, "source": "alibaba", "model": "MC2", "media": "ssd",
     "capacity_bytes": None, "drive_count": 52000},
)  # fmt: skip


def _quarter_index(day: date) -> int:
    return day.year * 4 + (day.month - 1) // 3


def periods(date_from: str, date_to: str, granularity: str) -> list[str]:
    """Period labels covering ``[from, to]``: ``YYYYQn`` or ``YYYY-MM``."""
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if granularity == "quarter":
        return [
            f"{q // 4}Q{q % 4 + 1}" for q in range(_quarter_index(start), _quarter_index(end) + 1)
        ]
    first, last = start.year * 12 + start.month - 1, end.year * 12 + end.month - 1
    return [f"{m // 12}-{m % 12 + 1:02d}" for m in range(first, last + 1)]


def _problem(status: int, title: str, detail: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"type": "about:blank", "title": title, "status": status, "detail": detail},
        headers={"content-type": "application/problem+json"},
    )


def _afr(failures: float, drive_days: int) -> float:
    return failures * 365 * 100 / drive_days


class FakeFleetApi:
    """In-process stand-in for fleet-api.

    Args:
        models: rows for ``GET /v1/models`` (defaults to six realistic models).
        failed_drives: number of failed drives each cohort reports in a window.
        override: optional ``(request) -> response | None``; a response short-circuits routing
            (use it to inject errors).
    """

    def __init__(
        self,
        models: list[dict[str, Any]] | None = None,
        *,
        failed_drives: int = 3,
        override: Callable[[httpx.Request], httpx.Response | None] | None = None,
    ) -> None:
        self.models = list(DEFAULT_MODELS) if models is None else models
        self.failed_count = failed_drives
        self.override = override
        self.requests: list[httpx.Request] = []

    def client(self) -> FleetApiClient:
        """A :class:`FleetApiClient` whose HTTP calls are answered by this fake."""
        transport = httpx.MockTransport(self.handler)
        http = httpx.AsyncClient(transport=transport, base_url="http://fleet-api.test")
        return FleetApiClient(http_client=http)

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Route one request (the ``httpx.MockTransport`` handler)."""
        self.requests.append(request)
        if self.override is not None:
            injected = self.override(request)
            if injected is not None:
                return injected
        q = request.url.params
        parts = [unquote(p) for p in request.url.raw_path.decode().split("?")[0].split("/") if p]
        if parts == ["v1", "models"]:
            return self._models(q)
        if "from" in q and "to" in q:
            window_error = self._window_error(q["from"], q["to"])
            if window_error is not None:
                return window_error
        if parts == ["v1", "cohorts", "compare"]:
            return self._compare(q)
        if parts == ["v1", "fleet", "summary"]:
            return self._summary(q)
        if len(parts) == 5 and parts[:2] == ["v1", "cohorts"]:
            source, model, leaf = parts[2], parts[3], parts[4]
            if not any(m["source"] == source and m["model"] == model for m in self.models):
                return _problem(404, "Not Found", f"no model {model} in {source}")
            if leaf == "afr":
                return self._afr_series(source, model, q)
            if leaf == "smart-trend":
                return self._smart(source, model, q)
            if leaf == "failed-drives":
                return self._failed(q)
        return _problem(404, "Not Found", "no such route")

    @staticmethod
    def _window_error(date_from: str, date_to: str) -> httpx.Response | None:
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        if end < start or _quarter_index(end) - _quarter_index(start) + 1 > 8:
            return _problem(400, "Bad Request", "window must be 1 to 8 quarters with from <= to")
        return None

    def _models(self, q: httpx.QueryParams) -> httpx.Response:
        rows = [
            m
            for m in self.models
            if m["source"] == q.get("source") and ("media" not in q or m["media"] == q["media"])
        ]
        page, size = int(q.get("page", 0)), int(q.get("size", 100))
        return httpx.Response(
            200,
            json={
                "items": rows[page * size : (page + 1) * size],
                "page": page,
                "size": size,
                "total": len(rows),
            },
        )

    def _afr_series(self, source: str, model: str, q: httpx.QueryParams) -> httpx.Response:
        series = []
        for i, period in enumerate(periods(q["from"], q["to"], q["granularity"])):
            drive_days, failures = 98_189 + 1_000 * i, (i * 7) % 5
            afr = _afr(failures, drive_days)
            series.append(
                {
                    "period": period,
                    "drive_days": drive_days,
                    "failures": failures,
                    "afr_pct": afr,
                    "ci_low_pct": afr * 0.41,
                    "ci_high_pct": afr * 2.3 + 1.37,
                }
            )
        body = {"source": source, "model": model, "series": series}
        return httpx.Response(200, json=body | {"method": METHOD, "generated_at": GENERATED_AT})

    def _compare(self, q: httpx.QueryParams) -> httpx.Response:
        min_drives, limit = int(q.get("min_drives", 60)), int(q.get("limit", 20))
        rows = []
        for m in self.models:
            if m["source"] != q["source"] or m["drive_count"] < min_drives:
                continue
            drive_days = m["drive_count"] * 90
            failures = m["id"] * 3
            afr = _afr(failures, drive_days)
            rows.append(
                {
                    "model": m["model"],
                    "drive_days": drive_days,
                    "failures": failures,
                    "afr_pct": afr,
                    "ci_low_pct": afr * 0.7,
                    "ci_high_pct": afr * 1.4,
                    "rate_ratio_vs_fleet": afr / 1.37,
                }
            )
        rows.sort(key=lambda r: (-r["afr_pct"], r["model"]))
        body = {"source": q["source"], "from": q["from"], "to": q["to"], "items": rows[:limit]}
        return httpx.Response(200, json=body | {"method": METHOD, "generated_at": GENERATED_AT})

    def _summary(self, q: httpx.QueryParams) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "source": q["source"],
                "from": q["from"],
                "to": q["to"],
                "drives": 301_234,
                "drive_days": 27_000_000,
                "failures": 1_012,
                "afr_pct": _afr(1_012, 27_000_000),
                "ci_low_pct": 1.288,
                "ci_high_pct": 1.457,
                "method": METHOD,
                "generated_at": GENERATED_AT,
            },
        )

    def _smart(self, source: str, model: str, q: httpx.QueryParams) -> httpx.Response:
        series = [
            {"period": p, "p50": 0.0, "p95": 8.0 + i, "nonzero_share": 0.031, "n_drives": 120}
            for i, p in enumerate(periods(q["from"], q["to"], q["granularity"]))
        ]
        body = {"source": source, "model": model, "attr": int(q["attr"]), "series": series}
        return httpx.Response(200, json=body | {"generated_at": GENERATED_AT})

    def _failed(self, q: httpx.QueryParams) -> httpx.Response:
        page, size = int(q.get("page", 0)), int(q.get("size", 100))
        rows = [
            {
                "drive_id": f"ZL2{i:05d}",
                "failed_on": f"2026-05-{i % 28 + 1:02d}",
                "age_days": 900 + i,
                "last_smart": {
                    str(a): float(a * 1_000_003 + i) if a in (9, 240, 241, 242) else float(i % 3)
                    for a in HDD_ATTRS
                },
            }
            for i in range(self.failed_count)
        ]
        return httpx.Response(
            200,
            json={
                "items": rows[page * size : (page + 1) * size],
                "page": page,
                "size": size,
                "total": len(rows),
            },
        )
