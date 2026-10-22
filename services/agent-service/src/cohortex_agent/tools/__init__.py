"""Tool gateway: MCP adapter (ADR-012) and an in-memory fake with the same envelope."""

from cohortex_agent.tools.base import (
    ToolCallError,
    ToolGateway,
    ToolSpec,
    split_llm_name,
)
from cohortex_agent.tools.fake import FakeToolGateway
from cohortex_agent.tools.mcp_gateway import McpToolGateway

__all__ = [
    "FakeToolGateway",
    "McpToolGateway",
    "ToolCallError",
    "ToolGateway",
    "ToolSpec",
    "split_llm_name",
]
