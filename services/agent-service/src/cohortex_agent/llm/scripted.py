"""Scripted provider for tests: responses come from per-node queues or a function."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from cohortex_agent.llm.base import LLMRequest, LLMResponse, ToolCall, Usage

ScriptItem = LLMResponse | Callable[[LLMRequest], LLMResponse]


def text(content: str | dict[str, Any] | list[Any], input_tokens: int = 100) -> LLMResponse:
    """A plain or JSON text response."""
    body = content if isinstance(content, str) else json.dumps(content)
    return LLMResponse(text=body, usage=Usage(input_tokens=input_tokens, output_tokens=20))


def tool_calls(*calls: tuple[str, dict[str, Any]], input_tokens: int = 100) -> LLMResponse:
    """A response asking for one or more tool calls: `tool_calls(("fleet_cohort_afr", {...}))`."""
    return LLMResponse(
        text="",
        tool_calls=[
            ToolCall(id=f"call_{i}_{name}", name=name, arguments=json.dumps(args))
            for i, (name, args) in enumerate(calls)
        ],
        usage=Usage(input_tokens=input_tokens, output_tokens=20),
    )


class ScriptExhaustedError(AssertionError):
    pass


class ScriptedProvider:
    """Pops the next scripted item for the request's node (`worker:*` falls back to `worker`).

    Items may be callables, which receive the request (to simulate a model reacting to input).
    Every request is kept in `requests` for assertions.
    """

    def __init__(
        self,
        script: Mapping[str, Iterable[ScriptItem]] | None = None,
        *,
        model_id: str = "scripted-model",
        default: ScriptItem | None = None,
    ) -> None:
        self._queues: dict[str, deque[ScriptItem]] = defaultdict(deque)
        for node, items in (script or {}).items():
            self._queues[node].extend(items)
        self._default = default
        self._model = model_id
        self.requests: list[LLMRequest] = []

    @property
    def model_id(self) -> str:
        return self._model

    def add(self, node: str, *items: ScriptItem) -> None:
        self._queues[node].extend(items)

    def calls_for(self, node: str) -> list[LLMRequest]:
        return [r for r in self.requests if r.node == node]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        queue = self._queues.get(request.node)
        if not queue and request.node.startswith("worker:"):
            queue = self._queues.get("worker")
        if queue:
            item = queue.popleft()
        elif self._default is not None:
            item = self._default
        else:
            raise ScriptExhaustedError(f"no scripted response left for node {request.node!r}")
        return item(request) if callable(item) else item
