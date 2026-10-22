"""HTTP API end to end (FR-AGT-1, NFR-SEC-4, NFR-REL-2, FR-OPS-4) over ASGI, real Postgres."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from agent_support import QUESTION, make_settings, parse_sse, single_script
from cohortex_agent.app import create_app
from cohortex_agent.llm.base import LLMProvider
from cohortex_agent.llm.scripted import ScriptedProvider
from cohortex_agent.tools.fake import FakeToolGateway
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.asyncio

Client = httpx.AsyncClient


@asynccontextmanager
async def api(
    database_url: str, provider: LLMProvider | None = None, **overrides: Any
) -> AsyncIterator[Client]:
    settings = make_settings(database_url, **overrides)
    app = create_app(settings, provider=provider or ScriptedProvider({}), gateway=FakeToolGateway())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://agent") as client:
            yield client


async def stream_events(client: Client, investigation_id: str) -> list[tuple[str, dict[str, Any]]]:
    response = await client.get(f"/v1/investigations/{investigation_id}/events", timeout=30)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


async def test_post_then_stream_steps_then_report(database_url: str) -> None:  # FR-AGT-1
    async with api(database_url, single_script()) as client:
        created = await client.post(
            "/v1/investigations",
            json={
                "question": QUESTION,
                "scope": {"source": "backblaze", "models": ["ST12000NM000J"], "from": "2026-01-01"},
            },
        )
        assert created.status_code == 202
        body = created.json()
        assert body["status"] == "queued"
        investigation_id = body["id"]

        events = await stream_events(client, investigation_id)
        names = [name for name, _ in events]
        assert names[-1] == "report"
        assert set(names[:-1]) == {"step"}
        steps = [data for name, data in events if name == "step"]
        assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
        assert [s["kind"] for s in steps] == ["tool_call", "tool_call", "draft", "check", "report"]
        tool_step = steps[0]
        assert tool_step["node"] == "agent"
        assert set(tool_step["payload"]) == {"tool", "args", "evidence_id", "ok", "summary"}
        assert tool_step["payload"]["tool"] == "fleet.cohort_afr"
        assert set(steps[3]["payload"]) == {"supported", "unsupported", "notes"}
        final = events[-1][1]
        assert final["status"] == "completed"
        assert final["report"]["summary"][0]["status"] == "supported"
        assert "## Limitations" in final["markdown"]

        view = (await client.get(f"/v1/investigations/{investigation_id}")).json()
        assert view["status"] == "completed"
        assert view["mode"] == "single"
        assert view["llm_model"] == "scripted-model"
        assert view["scope"]["date_from"] == "2026-01-01"
        assert view["report"] == final["report"]
        assert view["markdown"] == final["markdown"]
        assert view["tokens_in"] > 0
        assert view["cost_usd"] == 0.0
        assert view["finished_at"] is not None

        evidence_id = tool_step["payload"]["evidence_id"]
        evidence = await client.get(f"/v1/investigations/{investigation_id}/evidence/{evidence_id}")
        assert evidence.status_code == 200
        ev = evidence.json()
        assert ev["tool"] == "fleet.cohort_afr"
        assert ev["args"]["model"] == "ST12000NM000J"
        assert ev["result"]["evidence_id"] == evidence_id
        assert ev["result"]["data"]["series"][1]["failures"] == 9

        # Reconnecting after the run replays the stored steps and the report.
        assert await stream_events(client, investigation_id) == events

        recent = (await client.get("/v1/investigations?limit=5")).json()
        assert recent[0]["id"] == investigation_id


async def test_not_found_and_validation_use_problem_details(database_url: str) -> None:
    async with api(database_url) as client:
        for path in (
            f"/v1/investigations/{uuid.uuid4()}",
            "/v1/investigations/not-a-uuid",
            f"/v1/investigations/{uuid.uuid4()}/events",
            f"/v1/investigations/{uuid.uuid4()}/evidence/ev_0000000000000000",
        ):
            response = await client.get(path)
            assert response.status_code == 404, path
            assert response.headers["content-type"] == "application/problem+json"
            assert response.json()["status"] == 404
        bad = await client.post("/v1/investigations", json={"question": "x", "mode": "swarm"})
        assert bad.status_code == 422
        assert bad.headers["content-type"] == "application/problem+json"
        assert "mode" in bad.json()["detail"]


async def wait_for(check: Callable[[], bool]) -> None:
    import asyncio

    for _ in range(100):
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")


async def test_demo_mode_rate_limits_and_forces_the_public_mode(database_url: str) -> None:
    async with api(
        database_url,
        env="demo",
        admin_token="s3cret",  # noqa: S106 - test-only token
        public_mode="single",
    ) as client:  # NFR-SEC-4
        refused_question = {"question": "Which drive should I buy?", "mode": "orchestrated"}
        ids = []
        for _ in range(5):
            response = await client.post("/v1/investigations", json=refused_question)
            assert response.status_code == 202
            ids.append(response.json()["id"])
        limited = await client.post("/v1/investigations", json=refused_question)
        assert limited.status_code == 429
        assert limited.headers["content-type"] == "application/problem+json"
        assert "5 investigations per day" in limited.json()["detail"]

        wrong = await client.post(
            "/v1/investigations",
            json=refused_question,
            headers={"Authorization": "Bearer nope"},
        )
        assert wrong.status_code == 429
        admin = await client.post(
            "/v1/investigations", json=refused_question, headers={"Authorization": "Bearer s3cret"}
        )
        assert admin.status_code == 202

        for investigation_id in ids:
            events = await stream_events(client, investigation_id)
            assert events[-1][1]["status"] == "refused"
        public = (await client.get(f"/v1/investigations/{ids[0]}")).json()
        assert public["mode"] == "single"  # forced, although the body asked for orchestrated
        await stream_events(client, admin.json()["id"])
        owner = (await client.get(f"/v1/investigations/{admin.json()['id']}")).json()
        assert owner["mode"] == "orchestrated"


@pytest.mark.parametrize(
    "scope",
    [
        {"source": "alibaba", "models": ["MA1"], "from": "2018-01-01", "to": "2018-12-31"},
        {
            "source": "alibaba",
            "models": ["MA1"],
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
        },
    ],
)
async def test_scope_accepts_both_contract_shapes(database_url: str, scope: dict[str, Any]) -> None:
    async with api(database_url) as client:
        created = await client.post(
            "/v1/investigations", json={"question": "Which drive should I buy?", "scope": scope}
        )
        assert created.status_code == 202
        await stream_events(client, created.json()["id"])
        view = (await client.get(f"/v1/investigations/{created.json()['id']}")).json()
        expected = {
            "source": "alibaba",
            "models": ["MA1"],
            "date_from": "2018-01-01",
            "date_to": "2018-12-31",
        }
        assert view["scope"] == expected  # stored and returned in the contracts §6 shape
        assert view["report"]["scope"] == expected
        bad = await client.post(
            "/v1/investigations", json={"question": "q?!", "scope": {"start": "2018-01-01"}}
        )
        assert bad.status_code == 422


async def test_local_mode_is_not_rate_limited(database_url: str) -> None:
    async with api(database_url) as client:
        for _ in range(7):
            response = await client.post(
                "/v1/investigations", json={"question": "Which drive should I buy?"}
            )
            assert response.status_code == 202


async def test_startup_marks_stale_running_investigations_failed(database_url: str) -> None:
    stale, fresh = str(uuid.uuid4()), str(uuid.uuid4())
    now = datetime.now(UTC)
    with psycopg.connect(database_url) as conn:
        for investigation_id, started in ((stale, now - timedelta(hours=1)), (fresh, now)):
            conn.execute(
                b"INSERT INTO investigation (id, question, mode, status, llm_model,"
                b" prompt_hashes, started_at) VALUES (%s, 'q', 'single', 'running', 'm', %s, %s)",
                (investigation_id, Jsonb({}), started),
            )
    async with api(database_url, max_seconds=180):  # NFR-REL-2
        pass
    with psycopg.connect(database_url) as conn:
        statuses: dict[str, str] = dict(
            conn.execute(
                b"SELECT id::text, status FROM investigation WHERE id IN (%s, %s)", (stale, fresh)
            ).fetchall()
        )
    assert statuses == {stale: "failed", fresh: "running"}


async def test_suggested_investigations_from_open_alerts(database_url: str) -> None:
    alert_id = str(uuid.uuid4())
    with psycopg.connect(database_url) as conn:
        (model_id,) = conn.execute(
            b"INSERT INTO drive_model (source, model, media) VALUES ('backblaze', %s, 'hdd')"
            b" RETURNING id",
            (f"TEST{uuid.uuid4().hex[:6]}",),
        ).fetchone() or (None,)
        conn.execute(
            b"INSERT INTO alert (id, model_id, opened_at, window_start, window_end, baseline_afr,"
            b" current_afr, rate_ratio, p_value, status)"
            b" VALUES (%s, %s, now(), %s, %s, 1.2, 3.4, 2.83, 0.0004, 'open')",
            (alert_id, model_id, date(2026, 4, 1), date(2026, 6, 30)),
        )
    async with api(database_url) as client:
        alerts = (await client.get("/v1/alerts/suggested")).json()
    (mine,) = [a for a in alerts if a["alert_id"] == alert_id]
    assert mine["suggested_question"].startswith("Why did the annualized failure rate of backblaze")
    assert "from 1.20% to 3.40%" in mine["suggested_question"]
    assert mine["suggested_scope"]["models"] == [mine["model"]]
    assert mine["suggested_scope"]["date_from"] == "2026-04-01"


async def test_latest_eval_run(database_url: str) -> None:
    async with api(database_url) as client:
        assert (await client.get("/v1/evals/latest?mode=orchestrated")).status_code == 404
        with psycopg.connect(database_url) as conn:
            conn.execute(
                b"INSERT INTO eval_run (id, started_at, git_sha, golden_version, mode, llm_model,"
                b" recorded, metrics, passed) VALUES (%s, now(), 'abc', 'v1', 'orchestrated',"
                b" 'm', true, %s, true)",
                (str(uuid.uuid4()), Jsonb({"M1": 0.9})),
            )
        latest = await client.get("/v1/evals/latest?mode=orchestrated")
        assert latest.status_code == 200
        assert latest.json()["metrics"] == {"M1": 0.9}
        assert latest.json()["passed"] is True
        assert (await client.get("/v1/evals/latest?mode=bogus")).status_code == 422


async def test_health_and_readiness(database_url: str) -> None:  # FR-OPS-4
    async with api(database_url) as client:
        assert (await client.get("/healthz")).json() == {"status": "ok"}
        ready = await client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["database"] is True
        assert ready.json()["tools"] == 11
    async with api("postgresql://cohortex@localhost:1/none") as broken:
        response = await broken.get("/readyz")
        assert response.status_code == 503


async def test_cors_allows_the_web_ui_origin(database_url: str) -> None:
    async with api(database_url) as client:
        response = await client.options(
            "/v1/investigations",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
