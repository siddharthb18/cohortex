"""OpenAI-compatible provider: retries (NFR-REL-3), free-host cap (NFR-COST-2), parsing, spend."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import openai
import psycopg
import pytest
from agent_support import make_settings
from cohortex_agent.db import Database, PostgresSpendLedger
from cohortex_agent.llm.base import (
    LLMRequest,
    LLMUnavailableError,
    PaidEndpointRefusedError,
    SpendCapExceededError,
)
from cohortex_agent.llm.factory import build_provider
from cohortex_agent.llm.openai_compat import OpenAICompatibleProvider, check_free_host
from cohortex_agent.llm.recording import ReplayProvider

pytestmark = pytest.mark.asyncio

BASE_URL = "http://localhost:11434/v1"


def completion(content: str | None = "hi", **message: Any) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-oss:20b",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, **message},
            }
        ],
        "usage": {"prompt_tokens": 321, "completion_tokens": 12, "total_tokens": 333},
    }


class FaultyServer:
    """Serves a scripted sequence of HTTP responses and records each request."""

    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        return self.responses.pop(0)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class FakeLedger:
    def __init__(self, spent: float = 0.0) -> None:
        self.spent = spent
        self.added: list[float] = []

    async def month_to_date(self) -> float:
        return self.spent

    async def add(self, usd: float) -> None:
        self.added.append(usd)


def provider(server: FaultyServer, sleeps: Sleeps, **kwargs: Any) -> OpenAICompatibleProvider:
    client = openai.AsyncOpenAI(
        base_url=BASE_URL,
        api_key="ollama",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(server)),
    )
    return OpenAICompatibleProvider(
        base_url=BASE_URL,
        model="gpt-oss:20b",
        api_key="ollama",
        client=client,
        sleep=sleeps,
        **kwargs,
    )


REQUEST = LLMRequest(messages=[{"role": "user", "content": "hello"}], node="agent")


async def test_429_is_retried_honoring_retry_after() -> None:
    server = FaultyServer(
        httpx2.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow"}}),
        httpx2.Response(200, json=completion("ok")),
    )
    sleeps = Sleeps()
    response = await provider(server, sleeps).complete(REQUEST)
    assert response.text == "ok"
    assert sleeps.delays == [7.0]
    assert len(server.requests) == 2


async def test_5xx_is_retried_with_exponential_backoff_then_succeeds() -> None:
    server = FaultyServer(
        httpx2.Response(503, json={"error": {"message": "busy"}}),
        httpx2.Response(500, json={"error": {"message": "oops"}}),
        httpx2.Response(200, json=completion("ok")),
    )
    sleeps = Sleeps()
    response = await provider(server, sleeps, backoff_base_seconds=1.0).complete(REQUEST)
    assert response.text == "ok"
    assert len(sleeps.delays) == 2
    assert 1.0 <= sleeps.delays[0] < 1.25
    assert 2.0 <= sleeps.delays[1] < 2.25


async def test_gives_up_after_three_attempts() -> None:
    server = FaultyServer(*(httpx2.Response(502, json={}) for _ in range(5)))
    sleeps = Sleeps()
    with pytest.raises(LLMUnavailableError, match="after 3 attempts"):
        await provider(server, sleeps).complete(REQUEST)
    assert len(server.requests) == 3
    assert len(sleeps.delays) == 2


async def test_client_errors_are_not_retried() -> None:
    server = FaultyServer(httpx2.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(LLMUnavailableError, match="HTTP 400"):
        await provider(server, Sleeps()).complete(REQUEST)
    assert len(server.requests) == 1


async def test_groq_output_parse_failed_is_retried() -> None:
    bad = {"error": {"message": "Parsing failed", "code": "output_parse_failed"}}
    server = FaultyServer(
        httpx2.Response(400, json=bad), httpx2.Response(200, json=completion("ok"))
    )
    response = await provider(server, Sleeps()).complete(REQUEST)
    assert response.text == "ok"
    assert len(server.requests) == 2
    assert server.requests[1]["temperature"] == 0.6


async def test_output_cap_and_reasoning_effort_are_sent() -> None:
    server = FaultyServer(httpx2.Response(200, json=completion("ok")))
    await provider(server, Sleeps(), max_output_tokens=512, reasoning_effort="low").complete(
        REQUEST
    )
    body = server.requests[0]
    assert body["max_tokens"] == 512
    assert body["reasoning_effort"] == "low"


async def test_response_parsing_tokens_tool_calls_and_reasoning_ignored() -> None:
    body = completion(
        None,
        reasoning="internal chain of thought",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "fleet_cohort_afr", "arguments": '{"model": "X"}'},
            }
        ],
    )
    server = FaultyServer(httpx2.Response(200, json=body))
    ledger = FakeLedger()
    request = LLMRequest(
        messages=[{"role": "user", "content": "q"}],
        tools=[{"type": "function", "function": {"name": "fleet_cohort_afr", "parameters": {}}}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    response = await provider(server, Sleeps(), spend_ledger=ledger).complete(request)
    assert response.text is None
    assert [(c.id, c.name, c.parsed_arguments()) for c in response.tool_calls] == [
        ("call_1", "fleet_cohort_afr", {"model": "X"})
    ]
    assert (response.usage.input_tokens, response.usage.output_tokens) == (321, 12)
    assert response.cost_usd == 0.0
    assert ledger.added == [0.0]
    sent = server.requests[0]
    assert sent["model"] == "gpt-oss:20b"
    assert sent["temperature"] == 0.0
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["tools"][0]["function"]["name"] == "fleet_cohort_afr"


@pytest.mark.parametrize(
    "url",
    [
        "https://api.groq.com/openai/v1",
        "http://localhost:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://host.docker.internal:11434/v1",
        "http://ollama:11434/v1",
    ],
)
async def test_free_hosts_are_allowed_when_the_cap_is_zero(url: str) -> None:
    check_free_host(url, 0.0)


async def test_paid_host_is_refused_when_the_cap_is_zero() -> None:  # NFR-COST-2
    for url in ("https://api.openai.com/v1", "https://api.anthropic.com/v1"):
        with pytest.raises(PaidEndpointRefusedError):
            OpenAICompatibleProvider(base_url=url, model="m", api_key="k", monthly_cap_usd=0)
    settings = make_settings("postgresql://unused", llm_base_url="https://api.openai.com/v1")
    with pytest.raises(PaidEndpointRefusedError):
        build_provider(settings)
    # Extra free hosts can be allowlisted, and a positive cap lifts the allowlist.
    check_free_host("https://kaggle-tunnel.example.net/v1", 0.0, ("kaggle-tunnel.example.net",))
    check_free_host("https://api.openai.com/v1", 5.0)


async def test_positive_cap_is_enforced_by_the_spend_ledger() -> None:
    server = FaultyServer(httpx2.Response(200, json=completion()))
    with pytest.raises(SpendCapExceededError):
        await provider(
            server, Sleeps(), monthly_cap_usd=5.0, spend_ledger=FakeLedger(spent=5.0)
        ).complete(REQUEST)
    assert server.requests == []


async def test_spend_ledger_records_zero_in_postgres(database_url: str) -> None:
    ledger = PostgresSpendLedger(Database(database_url))
    await ledger.add(0.0)
    await ledger.add(0.0)
    assert await ledger.month_to_date() == 0.0
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(b"SELECT usd FROM llm_spend").fetchall()
    assert [float(r[0]) for r in rows] == [0.0]


async def test_replay_mode_needs_no_network_or_allowlist(tmp_path: Any) -> None:
    settings = make_settings(
        "postgresql://unused",
        llm_mode="replay",
        llm_base_url="https://api.openai.com/v1",
        recordings_dir=tmp_path,
    )
    assert isinstance(build_provider(settings), ReplayProvider)
