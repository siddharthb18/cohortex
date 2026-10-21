"""Build an MCP SDK 2.x low-level ``Server`` from tool specs, and run it over HTTP or stdio.

The low-level ``mcp.server.Server`` is used (not ``MCPServer``) because the input schemas and
descriptions must be the pinned contract files verbatim, not schemas derived from Python type
hints. The SDK does not validate tool arguments for low-level servers, so :class:`ToolRunner`
does it before any handler runs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import mcp_types as types
import uvicorn
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cohortex_mcp_common.contracts import ContractsNotFoundError, load_envelope_schema
from cohortex_mcp_common.envelope import ToolOutput, finalize, serialize
from cohortex_mcp_common.errors import ToolError
from cohortex_mcp_common.manifest import ManifestMismatchError, load_server_contracts
from cohortex_mcp_common.validation import ArgumentValidator

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2026-07-28"
"""The MCP revision these servers target. The SDK also answers older handshake-era clients."""

Handler = Callable[[dict[str, Any]], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class ToolSpec:
    """A tool implemented in code; its description and schema come from the manifest."""

    name: str
    handler: Handler


@dataclass(frozen=True)
class ToolCallOutcome:
    """Result body (envelope or error body) and whether it is an error."""

    body: dict[str, Any]
    is_error: bool

    def to_mcp(self) -> types.CallToolResult:
        """As an MCP ``CallToolResult``: JSON text content plus ``structuredContent``."""
        return types.CallToolResult(
            content=[types.TextContent(text=serialize(self.body))],
            structured_content=self.body,
            is_error=self.is_error,
        )


class ToolRunner:
    """Validates, runs and wraps tool calls for one server. Transport-independent."""

    def __init__(
        self, server: str, specs: Sequence[ToolSpec], contracts_base: Path | None = None
    ) -> None:
        self.server = server
        contracts = load_server_contracts(server, [s.name for s in specs], contracts_base)
        envelope_schema = load_envelope_schema(contracts_base)
        self._handlers = {spec.name: spec.handler for spec in specs}
        self._validators = {
            name: ArgumentValidator(c.input_schema) for name, c in contracts.items()
        }
        self.tools = [
            types.Tool(
                name=spec.name,
                title=contracts[spec.name].title,
                description=contracts[spec.name].description,
                input_schema=contracts[spec.name].input_schema,
                output_schema=envelope_schema,
                annotations=types.ToolAnnotations(
                    read_only_hint=True,
                    destructive_hint=False,
                    idempotent_hint=True,
                    open_world_hint=False,
                ),
            )
            for spec in specs
        ]

    async def call(self, name: str, arguments: Any) -> ToolCallOutcome:
        """Run one tool call; never raises, never returns a stack trace."""
        handler = self._handlers.get(name)
        if handler is None:
            return ToolCallOutcome(ToolError("not_found", "unknown tool").body(), True)
        try:
            args = self._validators[name].validate(arguments)
            output = await handler(args)
            return ToolCallOutcome(finalize(f"{self.server}.{name}", args, output), False)
        except ToolError as exc:
            return ToolCallOutcome(exc.body(), True)
        except Exception:  # boundary: log locally, return a generic structured error
            logger.exception("tool %s.%s failed", self.server, name)
            return ToolCallOutcome(ToolError("upstream_error", "internal tool error").body(), True)


def build_mcp_server(
    runner: ToolRunner, *, name: str, version: str, instructions: str | None = None
) -> Server[Any]:
    """Wrap a :class:`ToolRunner` in an MCP low-level ``Server`` (tools/list and tools/call)."""

    async def on_list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=runner.tools)

    async def on_call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        outcome = await runner.call(params.name, params.arguments)
        return outcome.to_mcp()

    return Server(
        name,
        version=version,
        instructions=instructions,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def build_http_app(server: Server[Any], *, host: str = "0.0.0.0") -> Starlette:  # noqa: S104
    """Streamable HTTP app: MCP at ``/mcp`` (stateless, JSON responses) plus ``GET /healthz``."""

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": server.name})

    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host=host,
        custom_starlette_routes=[Route("/healthz", healthz, methods=["GET"])],
    )


async def serve_stdio(server: Server[Any]) -> None:
    """Serve one MCP connection over this process's stdin/stdout."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_cli(
    argv: Sequence[str] | None,
    *,
    factory: Callable[[], Server[Any]],
    default_port: int,
    description: str,
) -> int:
    """Entry point shared by ``python -m cohortex_mcp_<name>``.

    Default: streamable HTTP on ``0.0.0.0:<default_port>`` at ``/mcp``. ``--stdio``: stdio.
    Returns 2 (and starts nothing) when the contracts are missing or a pinned hash mismatches.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--stdio", action="store_true", help="serve over stdin/stdout")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind address")  # noqa: S104
    parser.add_argument("--port", type=int, default=default_port, help="HTTP port")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        server = factory()
    except (ManifestMismatchError, ContractsNotFoundError) as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    if args.stdio:
        anyio.run(serve_stdio, server)
        return 0
    uvicorn.run(build_http_app(server, host=args.host), host=args.host, port=args.port)
    return 0
