"""Tool gateway interface (ADR-012) and naming rules (implementation-notes §6).

- MCP tool names are bare (`cohort_afr`).
- The envelope `tool` field is `<server>.<name>` (`fleet.cohort_afr`).
- The name shown to the LLM is `<server>_<name>` (`fleet_cohort_afr`): OpenAI-style function
  names cannot contain dots. Server names never contain underscores, so the split is unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

ServerName = Literal["fleet", "stats", "docs"]
SERVERS: tuple[str, ...] = ("fleet", "stats", "docs")
ERROR_CODES = ("invalid_argument", "not_found", "upstream_error", "too_large")


@dataclass(frozen=True)
class ToolSpec:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        return f"{self.server}.{self.name}"

    @property
    def llm_name(self) -> str:
        return f"{self.server}_{self.name}"

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.llm_name,
                "description": self.description,
                "parameters": compact_schema(self.input_schema),
            },
        }


# Keys the model does not need to call a tool correctly. The MCP server still validates every
# argument against the full pinned schema, so dropping them here only saves prompt tokens.
_LLM_SCHEMA_DROP = frozenset({"$schema", "$id", "title", "pattern", "minLength", "maxLength"})


def compact_schema(schema: Any) -> Any:
    """The input schema without validation-only keys, for the model's tool list."""
    if isinstance(schema, dict):
        return {k: compact_schema(v) for k, v in schema.items() if k not in _LLM_SCHEMA_DROP}
    if isinstance(schema, list):
        return [compact_schema(v) for v in schema]
    return schema


def split_llm_name(llm_name: str) -> tuple[str, str]:
    """`fleet_cohort_afr` -> (`fleet`, `cohort_afr`). Raises ValueError for unknown servers."""
    server, sep, name = llm_name.partition("_")
    if not sep or server not in SERVERS or not name:
        raise ValueError(f"unknown tool {llm_name!r}")
    return server, name


class ToolCallError(Exception):
    """A tool returned `isError` or could not be reached; `code` follows implementation-notes §6."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


@runtime_checkable
class ToolGateway(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, server: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Return the evidence envelope (contracts §5) or raise `ToolCallError`."""
        ...
