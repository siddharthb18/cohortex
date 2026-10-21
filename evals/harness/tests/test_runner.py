"""FR-EVAL-2: the runner drives a fake agent-service with bounded concurrency."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from cohortex_evals.cases import GoldenCase
from cohortex_evals.runner import RunConfig, run_cases
from cohortex_evals.testing import claim, evidence_body, make_report, number


def _case(i: int, **kw: Any) -> GoldenCase:
    data: dict[str, Any] = {
        "id": f"lookup-{i:04d}",
        "category": "lookup",
        "question": f"question {i}",
        "scope": {
            "source": "backblaze",
            "models": ["ST12000NM0008"],
            "date_from": "2026-04-01",
            "date_to": "2026-06-30",
        },
        "truth_sql": "SELECT 1",
        "primary_answer": {"field": "afr_pct", "unit": "pct", "abs_tol": 0.01},
        "must_refuse": False,
    }
    data.update(kw)
    return GoldenCase.model_validate(data)


@dataclass
class Inv:
    question: str
    polls_left: int
    status: str = "queued"


@dataclass
class FakeAgentService:
    """In-process stand-in for agent-service (contracts §4, implementation-notes §7)."""

    polls: int = 3
    final_status: str = "completed"
    never_finish: bool = False
    post_failures: list[int] = field(default_factory=list)  # status codes returned before 202
    investigations: dict[str, Inv] = field(default_factory=dict)
    posts: list[dict[str, Any]] = field(default_factory=list)
    evidence_gets: list[str] = field(default_factory=list)
    active: int = 0
    max_active: int = 0

    def report(self) -> dict[str, Any]:
        return make_report(
            summary=[
                claim("AFR was 1.5%.", [number(1.5, "pct", "ev_1", "series[0].afr_pct")]),
                claim("Missing evidence.", [number(2.0, "pct", "ev_404", "afr_pct")]),
            ]
        )

    async def handler(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        path = request.url.path
        if request.method == "POST" and path == "/v1/investigations":
            if self.post_failures:
                code = self.post_failures.pop(0)
                return httpx.Response(code, headers={"retry-after": "0"}, json={"title": "busy"})
            body = json.loads(request.content)
            self.posts.append(body)
            inv_id = str(uuid.uuid4())
            self.investigations[inv_id] = Inv(question=body["question"], polls_left=self.polls)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            return httpx.Response(202, json={"id": inv_id, "status": "queued"})
        parts = path.strip("/").split("/")
        if request.method == "GET" and len(parts) == 3:
            inv = self.investigations[parts[2]]
            if not self.never_finish and inv.status not in {
                "completed",
                "failed",
                "refused",
                "budget_exceeded",
            }:
                inv.polls_left -= 1
                inv.status = "running"
                if inv.polls_left <= 0:
                    inv.status = self.final_status
                    self.active -= 1
            done = inv.status == self.final_status and not self.never_finish
            return httpx.Response(
                200,
                json={
                    "id": parts[2],
                    "question": inv.question,
                    "scope": None,
                    "mode": "single",
                    "status": inv.status,
                    "llm_model": "gpt-oss-20b",
                    "started_at": "2026-10-21T00:00:00Z",
                    "finished_at": None,
                    "tokens_in": 1200 if done else None,
                    "tokens_out": 300 if done else None,
                    "cost_usd": "0.0000" if done else None,
                    "report": self.report() if done else None,
                    "markdown": "# Report" if done else None,
                },
            )
        if request.method == "GET" and len(parts) == 5 and parts[3] == "evidence":
            self.evidence_gets.append(parts[4])
            if parts[4] == "ev_1":
                return httpx.Response(
                    200, json=evidence_body("ev_1", {"series": [{"afr_pct": 1.5}]})
                )
            return httpx.Response(404, json={"title": "not found"})
        return httpx.Response(404)


FAST = RunConfig(mode="single", concurrency=2, poll_interval_s=0.001, retry_backoff_s=0.0)


@pytest.mark.asyncio
async def test_runner_completes_cases_and_fetches_summary_evidence() -> None:
    fake = FakeAgentService()
    runs = await run_cases(
        [_case(1)], "http://agent", FAST, transport=httpx.MockTransport(fake.handler)
    )
    (run,) = runs
    assert run.status == "completed"
    assert run.case_id == "lookup-0001"
    assert run.tokens_in == 1200
    assert run.tokens_out == 300
    assert run.cost_usd == 0.0
    assert run.llm_model == "gpt-oss-20b"
    assert run.latency_s is not None
    assert run.markdown == "# Report"
    assert set(run.evidence) == {"ev_1"}
    assert "ev_404" in run.evidence_errors
    assert fake.posts == [
        {
            "question": "question 1",
            "mode": "single",
            "scope": {
                "source": "backblaze",
                "models": ["ST12000NM0008"],
                "date_from": "2026-04-01",
                "date_to": "2026-06-30",
            },
        }
    ]


@pytest.mark.asyncio
async def test_concurrency_bound_is_respected() -> None:
    fake = FakeAgentService(polls=5)
    cases = [_case(i) for i in range(7)]
    runs = await run_cases(cases, "http://agent", FAST, transport=httpx.MockTransport(fake.handler))
    assert [r.case_id for r in runs] == [c.id for c in cases]  # order preserved
    assert all(r.status == "completed" for r in runs)
    assert fake.max_active == 2
    fake_one = FakeAgentService(polls=5)
    config = RunConfig(concurrency=1, poll_interval_s=0.001)
    await run_cases(
        cases[:3], "http://agent", config, transport=httpx.MockTransport(fake_one.handler)
    )
    assert fake_one.max_active == 1


@pytest.mark.asyncio
async def test_orchestrated_mode_and_no_scope() -> None:
    fake = FakeAgentService(polls=1)
    config = RunConfig(mode="orchestrated", poll_interval_s=0.001, send_scope=False)
    await run_cases([_case(1)], "http://agent", config, transport=httpx.MockTransport(fake.handler))
    assert fake.posts == [{"question": "question 1", "mode": "orchestrated"}]


@pytest.mark.asyncio
async def test_per_case_timeout() -> None:
    fake = FakeAgentService(never_finish=True)
    config = RunConfig(case_timeout_s=0.05, poll_interval_s=0.001)
    (run,) = await run_cases(
        [_case(1)], "http://agent", config, transport=httpx.MockTransport(fake.handler)
    )
    assert run.status == "timeout"
    assert run.investigation_id is not None
    assert run.error is not None
    assert "0.05" in run.error


@pytest.mark.asyncio
async def test_rate_limited_post_is_retried_and_server_error_reported() -> None:
    fake = FakeAgentService(polls=1, post_failures=[429, 503])
    (run,) = await run_cases(
        [_case(1)], "http://agent", FAST, transport=httpx.MockTransport(fake.handler)
    )
    assert run.status == "completed"
    broken = FakeAgentService(post_failures=[500])
    (run,) = await run_cases(
        [_case(1)], "http://agent", FAST, transport=httpx.MockTransport(broken.handler)
    )
    assert run.status == "error"
    assert run.error is not None
    assert "500" in run.error


@pytest.mark.asyncio
async def test_unreachable_service_is_an_error_not_a_crash() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    (run,) = await run_cases(
        [_case(1)], "http://agent", FAST, transport=httpx.MockTransport(refuse)
    )
    assert run.status == "error"
    assert "ConnectError" in (run.error or "")


@pytest.mark.asyncio
async def test_refused_status_is_terminal() -> None:
    fake = FakeAgentService(polls=1, final_status="refused")
    (run,) = await run_cases(
        [_case(1)], "http://agent", FAST, transport=httpx.MockTransport(fake.handler)
    )
    assert run.status == "refused"
