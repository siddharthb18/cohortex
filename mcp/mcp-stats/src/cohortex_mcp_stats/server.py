"""mcp-stats: the three pure statistics tools as an MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cohortex_mcp_common.envelope import ToolOutput
from cohortex_mcp_common.errors import ToolError
from cohortex_mcp_common.server import ToolRunner, ToolSpec, build_mcp_server
from mcp.server import Server

from cohortex_mcp_stats import __version__
from cohortex_mcp_stats.stats import StatsInputError, afr_ci, change_point, compare_rates

SERVER = "stats"
SERVER_NAME = "cohortex-mcp-stats"
DEFAULT_PORT = 8102
TOOL_NAMES = ("afr_ci", "compare_rates", "change_point")


async def _afr_ci(args: dict[str, Any]) -> ToolOutput:
    data = afr_ci(args["failures"], args["drive_days"], args["confidence"])
    return ToolOutput("mcp-stats afr_ci", data)


async def _compare_rates(args: dict[str, Any]) -> ToolOutput:
    try:
        data = compare_rates(
            args["failures_a"], args["drive_days_a"], args["failures_b"], args["drive_days_b"]
        )
    except StatsInputError as exc:
        raise ToolError("invalid_argument", str(exc)) from exc
    return ToolOutput("mcp-stats compare_rates", data)


async def _change_point(args: dict[str, Any]) -> ToolOutput:
    try:
        data = change_point(args["series"])
    except StatsInputError as exc:
        raise ToolError("invalid_argument", str(exc)) from exc
    return ToolOutput("mcp-stats change_point", data)


SPECS = (
    ToolSpec("afr_ci", _afr_ci),
    ToolSpec("compare_rates", _compare_rates),
    ToolSpec("change_point", _change_point),
)


def build_runner(contracts_base: Path | None = None) -> ToolRunner:
    """Transport-free runner (validation, envelope, errors). Raises on a manifest mismatch."""
    return ToolRunner(SERVER, SPECS, contracts_base)


def build_server(contracts_base: Path | None = None) -> Server[Any]:
    """The MCP server. Pass it to ``mcp.Client(server)`` for an in-memory session.

    Raises:
        ManifestMismatchError: a pinned description or schema hash does not match (FR-TOOL-5).
    """
    return build_mcp_server(build_runner(contracts_base), name=SERVER_NAME, version=__version__)
