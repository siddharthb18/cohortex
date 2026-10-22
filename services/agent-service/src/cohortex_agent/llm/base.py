"""The single provider interface every graph node uses (ADR-010).

Messages and tool specs use the OpenAI chat-completions wire format as plain dicts, because every
provider behind the interface is OpenAI-compatible (ADR-013) and plain dicts hash and record
cleanly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

Message = dict[str, Any]
ToolSpecJSON = dict[str, Any]


class LLMError(RuntimeError):
    """Base class for provider failures that end an LLM call."""


class LLMUnavailableError(LLMError):
    """The provider kept failing after all retry attempts (NFR-REL-3)."""


class PaidEndpointRefusedError(LLMError):
    """`LLM_BASE_URL` is not a free endpoint while the monthly cap is 0 (NFR-COST-2)."""


class SpendCapExceededError(LLMError):
    """The monthly spend ledger has reached `COHORTEX_MONTHLY_LLM_CAP_USD`."""


class RecordingMissing(LLMError):  # noqa: N818 - name fixed by the spec
    """Replay mode received a request that has no recorded response."""

    def __init__(self, key: str, node: str | None) -> None:
        super().__init__(f"no recorded response for request {key[:12]} (node={node})")
        self.key = key
        self.node = node


class StructuredOutputError(LLMError):
    """A JSON output still failed validation after the single repair attempt (ERS LLM rules)."""

    def __init__(self, node: str, errors: str, raw: str) -> None:
        super().__init__(f"{node}: structured output invalid after one repair: {errors[:300]}")
        self.node = node
        self.errors = errors
        self.raw = raw


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text exactly as the model produced it

    def parsed_arguments(self) -> dict[str, Any]:
        """Arguments as a dict; malformed JSON raises ValueError."""
        if not self.arguments.strip():
            return {}
        value = json.loads(self.arguments)
        if not isinstance(value, dict):
            raise ValueError("tool arguments must be a JSON object")
        return value

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class LLMRequest:
    messages: list[Message]
    tools: list[ToolSpecJSON] | None = None
    response_format: dict[str, Any] | None = None
    temperature: float = 0.0
    node: str = ""  # graph node, for logs and scripted tests; not part of the request hash

    def json_mode(self) -> bool:
        return bool(self.response_format and self.response_format.get("type") == "json_object")


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    cost_usd: float = 0.0

    def assistant_message(self) -> Message:
        """The response as an assistant message to append to the conversation."""
        message: Message = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
            },
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMResponse:
        usage = data.get("usage") or {}
        return cls(
            text=data.get("text"),
            tool_calls=[
                ToolCall(id=str(c["id"]), name=str(c["name"]), arguments=str(c["arguments"]))
                for c in data.get("tool_calls") or []
            ],
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
            model=str(data.get("model", "")),
        )


@runtime_checkable
class LLMProvider(Protocol):
    """One method; every implementation is configured by environment (ADR-010)."""

    @property
    def model_id(self) -> str: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_key(model: str, request: LLMRequest) -> str:
    """SHA-256 of the canonical JSON of {model, messages, tools, response_format, temperature}.

    Defined in docs/implementation-notes.md §7; recordings are looked up by this key.
    """
    payload = {
        "model": model,
        "messages": request.messages,
        "tools": request.tools,
        "response_format": request.response_format,
        "temperature": request.temperature,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
