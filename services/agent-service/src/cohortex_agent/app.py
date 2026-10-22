"""HTTP API (contracts §4, implementation-notes §7). Errors are RFC 9457 problem details."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette import EventSourceResponse, ServerSentEvent

from cohortex_agent import __version__
from cohortex_agent.config import Settings
from cohortex_agent.db import Database, PostgresSpendLedger
from cohortex_agent.events import EventBus
from cohortex_agent.ledger import step_data
from cohortex_agent.llm.base import LLMProvider
from cohortex_agent.llm.factory import build_provider
from cohortex_agent.prompts import PromptStore
from cohortex_agent.report import render_markdown
from cohortex_agent.runner import Investigator
from cohortex_agent.schemas import (
    TERMINAL_STATUSES,
    EvidenceView,
    InvestigationCreate,
    InvestigationCreated,
    InvestigationSummary,
    InvestigationView,
    Report,
    Scope,
    SuggestedAlert,
)
from cohortex_agent.tools.base import ToolGateway
from cohortex_agent.tools.fake import FakeToolGateway
from cohortex_agent.tools.fixtures import FixtureOverlayGateway
from cohortex_agent.tools.mcp_gateway import McpToolGateway

logger = logging.getLogger(__name__)
SSE_POLL_SECONDS = 10.0
_STATUSES = frozenset(s.value for s in HTTPStatus)


def build_gateway(settings: Settings) -> ToolGateway:
    gateway: ToolGateway
    if settings.tools_backend == "fake":
        gateway = FakeToolGateway()
    else:
        servers: dict[str, Any] = {
            "fleet": settings.mcp_fleet_url,
            "stats": settings.mcp_stats_url,
        }
        if settings.mcp_docs_url:
            servers["docs"] = settings.mcp_docs_url
        gateway = McpToolGateway(servers, timeout_seconds=settings.mcp_timeout_seconds)
    if settings.tool_fixtures_dir is not None:
        if settings.is_demo:
            logger.warning("COHORTEX_TOOL_FIXTURES_DIR is ignored in the demo environment")
        else:
            gateway = FixtureOverlayGateway(gateway, settings.tool_fixtures_dir)
    return gateway


class DailyRateLimiter:
    """In-memory per-IP daily counter for the public demo (NFR-SEC-4)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._counts: dict[tuple[str, date], int] = defaultdict(int)

    def hit(self, key: str) -> bool:
        today = datetime.now(UTC).date()
        for old in [k for k in self._counts if k[1] != today]:
            del self._counts[old]
        if self._counts[(key, today)] >= self.limit:
            return False
        self._counts[(key, today)] += 1
        return True


@dataclass
class Deps:
    settings: Settings
    db: Database
    bus: EventBus
    prompts: PromptStore
    gateway: ToolGateway
    investigator: Investigator
    limiter: DailyRateLimiter


def _problem(status: int, title: str, detail: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status}
    if detail:
        body["detail"] = detail
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal | int | float) else None


def _valid_id(investigation_id: str) -> str:
    try:
        return str(uuid.UUID(investigation_id))
    except ValueError:
        raise HTTPException(404, "investigation not found") from None


def suggested_question(alert: dict[str, Any]) -> str:
    return (
        f"Why did the annualized failure rate of {alert['source']} model {alert['model']} rise "
        f"from {float(alert['baseline_afr']):.2f}% to {float(alert['current_afr']):.2f}% "
        f"between {alert['window_start']} and {alert['window_end']} "
        f"(rate ratio {float(alert['rate_ratio']):.2f}, p = {float(alert['p_value']):.2g})?"
    )


def create_app(
    settings: Settings,
    *,
    provider: LLMProvider | None = None,
    gateway: ToolGateway | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_url)
        bus = EventBus()
        prompts = PromptStore(settings.prompts_dir)
        llm = provider or build_provider(settings, PostgresSpendLedger(db))
        tools = gateway or build_gateway(settings)
        investigator = Investigator(
            settings=settings, db=db, provider=llm, gateway=tools, prompts=prompts, bus=bus
        )
        try:  # restart safety (NFR-REL-2); a down database is reported by /readyz instead
            cutoff = datetime.now(UTC) - timedelta(seconds=settings.max_seconds)
            stale = await db.fail_stale(cutoff)
            if stale:
                logger.warning("marked stale investigations failed", extra={"count": stale})
        except psycopg.OperationalError as exc:
            logger.error("database unavailable at startup", extra={"err": str(exc)[:200]})
        app.state.deps = Deps(
            settings=settings,
            db=db,
            bus=bus,
            prompts=prompts,
            gateway=tools,
            investigator=investigator,
            limiter=DailyRateLimiter(settings.public_rate_limit_per_day),
        )
        try:
            yield
        finally:
            await investigator.shutdown()

    app = FastAPI(
        title="Cohortex agent-service",
        version=__version__,
        summary="Evidence-checked reliability investigations over public drive-fleet telemetry.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException) -> JSONResponse:
        title = HTTPStatus(exc.status_code).phrase if exc.status_code in _STATUSES else "Error"
        return _problem(exc.status_code, title, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:10]
        )
        return _problem(422, "Invalid request", detail)

    def deps(request: Request) -> Deps:
        value: Deps = request.app.state.deps
        return value

    def is_admin(request: Request, d: Deps) -> bool:
        token = d.settings.admin_token
        header = request.headers.get("authorization", "")
        return bool(token) and hmac.compare_digest(header.encode(), f"Bearer {token}".encode())

    def client_key(request: Request, d: Deps) -> str:
        if d.settings.trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    # ------------------------------------------------------------------ health

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"], response_model=None)
    async def readyz(request: Request) -> dict[str, Any] | JSONResponse:
        d = deps(request)
        checks: dict[str, Any] = {}
        try:
            checks["database"] = await d.db.ping()
        except Exception as exc:
            checks["database"] = False
            checks["database_error"] = type(exc).__name__
        try:
            checks["tools"] = len(await d.gateway.list_tools())
        except Exception:
            checks["tools"] = 0
        ready = checks["database"] is True and checks["tools"] > 0
        if not ready:
            return JSONResponse({"status": "not_ready", **checks}, status_code=503)
        return {"status": "ready", **checks}

    # ------------------------------------------------------------------ investigations

    @app.post(
        "/v1/investigations",
        status_code=202,
        response_model=InvestigationCreated,
        tags=["investigations"],
    )
    async def create_investigation(
        body: InvestigationCreate, request: Request
    ) -> InvestigationCreated:
        d = deps(request)
        mode = body.mode or d.settings.default_mode
        if d.settings.is_demo and not is_admin(request, d):
            if not d.limiter.hit(client_key(request, d)):
                raise HTTPException(
                    429,
                    f"public demo limit reached: {d.settings.public_rate_limit_per_day}"
                    " investigations per day",
                )
            mode = d.settings.public_mode
        scope = body.scope.to_scope() if body.scope else Scope()
        investigation_id = await d.investigator.start(body.question, scope, mode)
        return InvestigationCreated(id=investigation_id, status="queued")

    @app.get(
        "/v1/investigations", response_model=list[InvestigationSummary], tags=["investigations"]
    )
    async def list_investigations(
        request: Request, limit: int = Query(20, ge=1, le=100)
    ) -> list[InvestigationSummary]:
        rows = await deps(request).db.list_investigations(limit)
        return [InvestigationSummary.model_validate({**r, "id": str(r["id"])}) for r in rows]

    @app.get(
        "/v1/investigations/{investigation_id}",
        response_model=InvestigationView,
        tags=["investigations"],
    )
    async def get_investigation(investigation_id: str, request: Request) -> InvestigationView:
        d = deps(request)
        investigation_id = _valid_id(investigation_id)
        row = await d.db.get_investigation(investigation_id)
        if row is None:
            raise HTTPException(404, "investigation not found")
        report = Report.model_validate(row["report"]) if row["report"] else None
        markdown = None
        if report is not None:
            evidence = await d.db.evidence_results(investigation_id)
            markdown = render_markdown(report, status=row["status"], evidence=evidence)
        return InvestigationView(
            id=str(row["id"]),
            question=row["question"],
            scope=row["scope"],
            mode=row["mode"],
            status=row["status"],
            llm_model=row["llm_model"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            cost_usd=_to_float(row["cost_usd"]),
            report=report,
            markdown=markdown,
        )

    @app.get(
        "/v1/investigations/{investigation_id}/evidence/{evidence_id}",
        response_model=EvidenceView,
        tags=["investigations"],
    )
    async def get_evidence(
        investigation_id: str, evidence_id: str, request: Request
    ) -> EvidenceView:
        investigation_id = _valid_id(investigation_id)
        row = await deps(request).db.get_evidence(investigation_id, evidence_id)
        if row is None:
            raise HTTPException(404, "evidence not found")
        return EvidenceView(
            evidence_id=row["evidence_id"],
            tool=row["tool_name"],
            args=row["args"],
            result=row["result"],
            created_at=row["created_at"],
        )

    @app.get("/v1/investigations/{investigation_id}/events", tags=["investigations"])
    async def events(investigation_id: str, request: Request) -> EventSourceResponse:
        d = deps(request)
        investigation_id = _valid_id(investigation_id)
        if await d.db.get_investigation(investigation_id) is None:
            raise HTTPException(404, "investigation not found")
        return EventSourceResponse(_stream(d, investigation_id), ping=15)

    # ------------------------------------------------------------------ alerts and evals

    @app.get("/v1/alerts/suggested", response_model=list[SuggestedAlert], tags=["alerts"])
    async def suggested(request: Request) -> list[SuggestedAlert]:
        rows = await deps(request).db.open_alerts()
        return [
            SuggestedAlert(
                alert_id=str(r["id"]),
                source=r["source"],
                model=r["model"],
                opened_at=r["opened_at"],
                window_start=r["window_start"],
                window_end=r["window_end"],
                baseline_afr=r["baseline_afr"],
                current_afr=r["current_afr"],
                rate_ratio=r["rate_ratio"],
                p_value=r["p_value"],
                suggested_question=suggested_question(r),
                suggested_scope=Scope(
                    source=r["source"] if r["source"] in ("backblaze", "alibaba") else None,
                    models=[r["model"]],
                    date_from=r["window_start"],
                    date_to=r["window_end"],
                ),
            )
            for r in rows
        ]

    @app.get("/v1/evals/latest", tags=["evals"])
    async def latest_eval(
        request: Request, mode: str | None = Query(None, pattern="^(single|orchestrated)$")
    ) -> dict[str, Any]:
        row = await deps(request).db.latest_eval(mode)
        if row is None:
            raise HTTPException(404, "no eval run recorded")
        encoded: dict[str, Any] = jsonable_encoder(
            {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}
        )
        return encoded

    return app


def _sse(event: str, data: Any) -> ServerSentEvent:
    return ServerSentEvent(data=json.dumps(jsonable_encoder(data)), event=event)


def _step_data(row: dict[str, Any]) -> dict[str, Any]:
    return step_data(row)


async def _terminal(d: Deps, investigation_id: str) -> ServerSentEvent | None:
    row = await d.db.get_investigation(investigation_id)
    if row is None or row["status"] not in TERMINAL_STATUSES:
        return None
    if row["status"] == "failed" or not row["report"]:
        steps = await d.db.list_steps(investigation_id)
        errors = [s["payload"].get("message", "") for s in steps if s["kind"] == "error"]
        message = errors[-1] if errors else "investigation failed"
        return _sse("error", {"status": row["status"], "message": message})
    report = Report.model_validate(row["report"])
    evidence = await d.db.evidence_results(investigation_id)
    markdown = render_markdown(report, status=row["status"], evidence=evidence)
    return _sse(
        "report",
        {"status": row["status"], "report": report.model_dump(mode="json"), "markdown": markdown},
    )


async def _stream(d: Deps, investigation_id: str) -> AsyncIterator[ServerSentEvent]:
    """Replay stored steps, then follow live ones until the terminal `report` or `error`."""
    queue = d.bus.subscribe(investigation_id)
    last_seq = 0
    try:
        while True:
            for row in await d.db.list_steps(investigation_id):
                if row["seq"] > last_seq:
                    last_seq = row["seq"]
                    yield _sse("step", _step_data(row))
            terminal = await _terminal(d, investigation_id)
            if terminal is not None:
                # The run may have written its last steps between the two reads above.
                for row in await d.db.list_steps(investigation_id):
                    if row["seq"] > last_seq:
                        last_seq = row["seq"]
                        yield _sse("step", _step_data(row))
                yield terminal
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=SSE_POLL_SECONDS)
            except TimeoutError:
                continue  # re-check the database: the run may live in another process
            while True:
                if event["event"] == "step":
                    if event["data"]["seq"] > last_seq:
                        last_seq = event["data"]["seq"]
                        yield _sse("step", event["data"])
                else:
                    yield _sse(event["event"], event["data"])
                    return
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
    finally:
        d.bus.unsubscribe(investigation_id, queue)
