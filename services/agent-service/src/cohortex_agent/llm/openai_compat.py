"""OpenAI-compatible provider (Groq free tier, local Ollama, Ollama on Kaggle; ADR-013).

Responsibilities that live here and nowhere else (ADR-010):
- free-host allowlist while the monthly cap is 0 (NFR-COST-2, implementation-notes §7);
- timeouts and retries with exponential backoff that honor `Retry-After` (NFR-REL-3);
- token accounting from `usage`;
- the spend ledger (`llm_spend`), always charged $0 under ADR-013.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

import openai

from cohortex_agent.llm.base import (
    LLMRequest,
    LLMResponse,
    LLMUnavailableError,
    PaidEndpointRefusedError,
    SpendCapExceededError,
    ToolCall,
    Usage,
)

logger = logging.getLogger(__name__)

FREE_LLM_HOSTS: frozenset[str] = frozenset(
    {"api.groq.com", "localhost", "127.0.0.1", "host.docker.internal", "ollama"}
)
MAX_ATTEMPTS = 3
RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 60.0


class SpendLedger(Protocol):
    """Monthly spend store (`llm_spend` table)."""

    async def month_to_date(self) -> float: ...

    async def add(self, usd: float) -> None: ...


def check_free_host(base_url: str, cap_usd: float, extra_hosts: tuple[str, ...] = ()) -> None:
    """Refuse a non-allowlisted endpoint while the spend cap is 0."""
    if cap_usd > 0:
        return
    host = (urlsplit(base_url).hostname or "").lower()
    allowed = FREE_LLM_HOSTS | {h.lower() for h in extra_hosts}
    if host not in allowed:
        raise PaidEndpointRefusedError(
            f"LLM_BASE_URL host {host!r} is not a free endpoint and COHORTEX_MONTHLY_LLM_CAP_USD"
            f" is 0; allowed hosts: {sorted(allowed)} (add free hosts via COHORTEX_FREE_LLM_HOSTS)"
        )


def _retry_after_seconds(headers: Any) -> float | None:
    """Parse `Retry-After` (seconds or HTTP date) from response headers, if present."""
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    raw = str(raw).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


class OpenAICompatibleProvider:
    """`LLMProvider` over the `openai` SDK pointed at `LLM_BASE_URL`."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        monthly_cap_usd: float = 0.0,
        free_hosts: tuple[str, ...] = (),
        spend_ledger: SpendLedger | None = None,
        client: openai.AsyncOpenAI | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        backoff_base_seconds: float = 1.0,
    ) -> None:
        check_free_host(base_url, monthly_cap_usd, free_hosts)
        self._model = model
        self._cap = monthly_cap_usd
        self._ledger = spend_ledger
        self._sleep = sleep
        self._backoff = backoff_base_seconds
        # SDK retries are off: this class owns retry policy so it is testable and honors the cap.
        self._client = client or openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "not-needed",
            timeout=timeout_seconds,
            max_retries=0,
        )

    @property
    def model_id(self) -> str:
        return self._model

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self._ledger is not None and self._cap > 0:
            spent = await self._ledger.month_to_date()
            if spent >= self._cap:
                raise SpendCapExceededError(f"monthly LLM spend {spent:.4f} USD reached the cap")
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.tools:
            kwargs["tools"] = request.tools
        if request.response_format is not None:
            kwargs["response_format"] = request.response_format

        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                raw = await self._client.chat.completions.create(**kwargs)
            except openai.APIStatusError as exc:
                last_error = exc
                if exc.status_code not in RETRYABLE_STATUS and exc.status_code < 500:
                    raise LLMUnavailableError(
                        f"LLM request rejected: HTTP {exc.status_code}"
                    ) from exc
                delay = _retry_after_seconds(exc.response.headers)
            except (openai.APIConnectionError, openai.APITimeoutError) as exc:
                last_error = exc
                delay = None
            else:
                response = self._parse(raw)
                logger.info(
                    "llm call ok",
                    extra={
                        "node": request.node,
                        "attempt": attempt,
                        "latency_s": round(time.monotonic() - started, 3),
                        "input_tokens": response.usage.input_tokens,
                    },
                )
                if self._ledger is not None:
                    await self._ledger.add(response.cost_usd)  # always 0 under ADR-013
                return response
            if attempt == MAX_ATTEMPTS:
                break
            if delay is None:
                delay = self._backoff * (2 ** (attempt - 1)) + random.uniform(0, self._backoff / 4)  # noqa: S311
            delay = min(delay, MAX_RETRY_AFTER_SECONDS)
            logger.warning(
                "llm call failed; retrying",
                extra={"node": request.node, "attempt": attempt, "delay_s": delay},
            )
            await self._sleep(delay)
        raise LLMUnavailableError(f"LLM unavailable after {MAX_ATTEMPTS} attempts: {last_error}")

    def _parse(self, raw: Any) -> LLMResponse:
        data: dict[str, Any] = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        choices = data.get("choices") or []
        message: dict[str, Any] = (choices[0].get("message") if choices else None) or {}
        tool_calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if not function.get("name"):
                continue  # non-function tool calls are not used by Cohortex
            tool_calls.append(
                ToolCall(
                    id=str(call.get("id") or f"call_{len(tool_calls)}"),
                    name=str(function["name"]),
                    arguments=str(function.get("arguments") or "{}"),
                )
            )
        usage = data.get("usage") or {}
        # gpt-oss models also return `reasoning`; it is deliberately ignored.
        return LLMResponse(
            text=message.get("content"),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
            model=str(data.get("model") or self._model),
            cost_usd=0.0,
        )
