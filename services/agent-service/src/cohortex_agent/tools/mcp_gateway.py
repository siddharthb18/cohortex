"""Thin MCP adapter over the MCP Python SDK 2.x `Client` (ADR-012).

One short-lived `Client` per call: the 2026-07-28 protocol is stateless, and a per-call client
never shares anyio cancel scopes between the investigation tasks that run in parallel.
Tool listings are cached per server after the first successful `tools/list`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from mcp.types import CallToolResult, TextContent

from cohortex_agent.tools.base import ToolCallError, ToolSpec
from mcp import Client, MCPError

logger = logging.getLogger(__name__)


def _text_of(result: CallToolResult) -> str:
    return "".join(block.text for block in result.content if isinstance(block, TextContent))


def _payload(result: CallToolResult) -> Any:
    payload: Any = result.structured_content
    if payload is None:
        body = _text_of(result)
        try:
            payload = json.loads(body) if body.strip() else None
        except json.JSONDecodeError:
            payload = {"text": body}
    # MCPServer wraps non-object return values as {"result": ...}.
    if isinstance(payload, dict) and set(payload) == {"result"}:
        payload = payload["result"]
    return payload


def envelope_from_result(
    result: CallToolResult, server: str, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Turn an MCP tool result into the contracts §5 envelope, or raise `ToolCallError`."""
    payload = _payload(result)
    if result.is_error:
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            raise ToolCallError(str(error.get("code", "upstream_error")), str(error.get("message")))
        raise ToolCallError("upstream_error", _text_of(result)[:300] or "tool reported an error")
    if isinstance(payload, dict) and "data" in payload and "tool" in payload:
        envelope = dict(payload)
    else:  # tolerate a server that returns bare data
        envelope = {
            "evidence_id": "",
            "tool": f"{server}.{name}",
            "args": args,
            "source": f"mcp-{server}",
            "generated_at": datetime.now(UTC).isoformat(),
            "data": payload,
            "truncated": False,
            "next_page": None,
        }
    envelope.setdefault("truncated", False)
    envelope.setdefault("next_page", None)
    return envelope


class McpToolGateway:
    """`ToolGateway` over MCP servers reached by URL (streamable HTTP) or in-process (tests).

    `servers` maps server name (`fleet`, `stats`, `docs`) to whatever `mcp.Client` accepts:
    a URL string such as `http://localhost:8101/mcp`, or an `MCPServer` instance.
    """

    def __init__(self, servers: Mapping[str, Any], *, timeout_seconds: float = 30.0) -> None:
        self._servers = dict(servers)
        self._timeout = timeout_seconds
        self._specs: dict[str, list[ToolSpec]] = {}
        self._lock = asyncio.Lock()

    @property
    def server_names(self) -> list[str]:
        return list(self._servers)

    async def list_tools(self) -> list[ToolSpec]:
        async with self._lock:
            for server, target in self._servers.items():
                if server in self._specs:
                    continue
                try:
                    self._specs[server] = await self._list(server, target)
                except Exception as exc:  # unreachable server: skip it, retry on the next listing
                    logger.warning(
                        "mcp tools/list failed", extra={"server": server, "err": str(exc)}
                    )
            return [spec for server in self._servers for spec in self._specs.get(server, [])]

    async def _list(self, server: str, target: Any) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        async with Client(target, read_timeout_seconds=self._timeout) as client:
            cursor: str | None = None
            while True:
                listing = await client.list_tools(cursor=cursor)
                specs.extend(
                    ToolSpec(
                        server=server,
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=dict(tool.input_schema),
                    )
                    for tool in listing.tools
                )
                cursor = listing.next_cursor
                if not cursor:
                    return specs

    async def call(self, server: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        target = self._servers.get(server)
        if target is None:
            raise ToolCallError("not_found", f"MCP server {server!r} is not configured")
        try:
            async with Client(target, read_timeout_seconds=self._timeout) as client:
                result = await client.call_tool(name, args, read_timeout_seconds=self._timeout)
        except ToolCallError:
            raise
        except MCPError as exc:
            raise ToolCallError("invalid_argument", str(exc)[:300]) from exc
        except Exception as exc:
            raise ToolCallError("upstream_error", f"{type(exc).__name__}: {exc}"[:300]) from exc
        return envelope_from_result(result, server, name, args)
