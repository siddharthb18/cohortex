"""LLM provider interface and implementations (ADR-010, ADR-013)."""

from cohortex_agent.llm.base import (
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUnavailableError,
    PaidEndpointRefusedError,
    RecordingMissing,
    SpendCapExceededError,
    StructuredOutputError,
    ToolCall,
    Usage,
    request_key,
)
from cohortex_agent.llm.openai_compat import OpenAICompatibleProvider, check_free_host
from cohortex_agent.llm.recording import RecordingProvider, ReplayProvider
from cohortex_agent.llm.scripted import ScriptedProvider

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMUnavailableError",
    "OpenAICompatibleProvider",
    "PaidEndpointRefusedError",
    "RecordingMissing",
    "RecordingProvider",
    "ReplayProvider",
    "ScriptedProvider",
    "SpendCapExceededError",
    "StructuredOutputError",
    "ToolCall",
    "Usage",
    "check_free_host",
    "request_key",
]
