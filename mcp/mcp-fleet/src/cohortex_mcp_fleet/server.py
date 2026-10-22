"""mcp-fleet: six read-only tools over fleet-api (ADR-002), as an MCP server."""

from __future__ import annotations

import difflib
from datetime import date
from pathlib import Path
from typing import Any

from cohortex_mcp_common.envelope import Paging, ToolOutput
from cohortex_mcp_common.errors import ToolError
from cohortex_mcp_common.server import ToolRunner, ToolSpec, build_mcp_server
from mcp.server import Server

from cohortex_mcp_fleet import __version__
from cohortex_mcp_fleet.client import MAX_PAGE_SIZE, FleetApiClient, FleetApiError

SERVER = "fleet"
SERVER_NAME = "cohortex-mcp-fleet"
DEFAULT_PORT = 8101
TOOL_NAMES = (
    "list_models",
    "cohort_afr",
    "compare_cohorts",
    "fleet_summary",
    "smart_trend",
    "failed_drives",
)

MAX_WINDOW_QUARTERS = 8
LIST_MODELS_MAX_ROWS = 100
FAILED_DRIVES_PER_PAGE = 25
FAILED_DRIVES_MAX_ROWS = MAX_PAGE_SIZE
"""failed_drives pages over one fleet-api page of 500 rows (fleet-api's maximum page size)."""
_MAX_MODEL_FETCH_PAGES = 20
KEPT_SMART_ATTRS = {
    "backblaze": frozenset({5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242}),
    "alibaba": frozenset({5, 9, 12, 171, 172, 173, 174, 175, 187, 188, 194, 195, 199}),
}
_MODEL_FIELDS = ("model", "media", "capacity_bytes", "drive_count")


def _quarter(day: date) -> int:
    return day.year * 4 + (day.month - 1) // 3


def check_window(args: dict[str, Any]) -> tuple[str, str]:
    """``[from, to]`` inclusive, ``from <= to``, at most 8 calendar quarters (FR-API-8)."""
    start, end = date.fromisoformat(args["from"]), date.fromisoformat(args["to"])
    if end < start:
        raise ToolError("invalid_argument", "'to' must not be before 'from'")
    spanned = _quarter(end) - _quarter(start) + 1
    if spanned > MAX_WINDOW_QUARTERS:
        raise ToolError(
            "invalid_argument",
            f"window spans {spanned} quarters; at most {MAX_WINDOW_QUARTERS} are allowed",
        )
    return args["from"], args["to"]


class FleetTools:
    """The tool handlers, bound to one :class:`FleetApiClient`."""

    def __init__(self, fleet: FleetApiClient) -> None:
        self.fleet = fleet

    async def list_models(self, args: dict[str, Any]) -> ToolOutput:
        rows: list[dict[str, Any]] = []
        for page in range(_MAX_MODEL_FETCH_PAGES):
            batch = await self.fleet.list_models(args["source"], args.get("media"), page)
            rows.extend(item.model_dump(mode="json") for item in batch.items)
            if not batch.items or len(rows) >= batch.total:
                break
        if "media" in args:
            rows = [r for r in rows if r["media"] == args["media"]]
        if "min_drives" in args:
            rows = [r for r in rows if r["drive_count"] >= args["min_drives"]]
        rows.sort(key=lambda r: (-r["drive_count"], r["model"]))
        kept = [{key: r.get(key) for key in _MODEL_FIELDS} for r in rows[:LIST_MODELS_MAX_ROWS]]
        return ToolOutput(
            "fleet-api /v1/models",
            kept,
            Paging(None, capped=len(rows) > LIST_MODELS_MAX_ROWS),
        )

    async def cohort_afr(self, args: dict[str, Any]) -> ToolOutput:
        date_from, date_to = check_window(args)
        body = await self.fleet.cohort_afr(
            args["source"], args["model"], date_from, date_to, args["granularity"]
        )
        return ToolOutput(
            "fleet-api /v1/cohorts/{source}/{model}/afr",
            body.model_dump(mode="json"),
            Paging("series"),
        )

    async def compare_cohorts(self, args: dict[str, Any]) -> ToolOutput:
        date_from, date_to = check_window(args)
        body = await self.fleet.compare(
            args["source"], date_from, date_to, args["min_drives"], args["limit"]
        )
        data = body.model_dump(mode="json")
        data["items"] = data["items"][: args["limit"]]
        return ToolOutput("fleet-api /v1/cohorts/compare", data, Paging("items"))

    async def fleet_summary(self, args: dict[str, Any]) -> ToolOutput:
        date_from, date_to = check_window(args)
        body = await self.fleet.fleet_summary(args["source"], date_from, date_to)
        return ToolOutput("fleet-api /v1/fleet/summary", body.model_dump(mode="json"))

    async def smart_trend(self, args: dict[str, Any]) -> ToolOutput:
        if args["attr"] not in KEPT_SMART_ATTRS[args["source"]]:
            kept = ", ".join(str(a) for a in sorted(KEPT_SMART_ATTRS[args["source"]]))
            raise ToolError(
                "invalid_argument", f"attr {args['attr']} is not kept for {args['source']}: {kept}"
            )
        date_from, date_to = check_window(args)
        body = await self.fleet.smart_trend(
            args["source"], args["model"], args["attr"], date_from, date_to, args["granularity"]
        )
        return ToolOutput(
            "fleet-api /v1/cohorts/{source}/{model}/smart-trend",
            body.model_dump(mode="json"),
            Paging("series"),
        )

    async def failed_drives(self, args: dict[str, Any]) -> ToolOutput:
        date_from, date_to = check_window(args)
        body = await self.fleet.failed_drives(
            args["source"], args["model"], date_from, date_to, page=0, size=FAILED_DRIVES_MAX_ROWS
        )
        items = [item.model_dump(mode="json") for item in body.items[:FAILED_DRIVES_MAX_ROWS]]
        return ToolOutput(
            "fleet-api /v1/cohorts/{source}/{model}/failed-drives",
            {"total": body.total, "items": items},
            Paging(
                "items",
                max_rows_per_page=FAILED_DRIVES_PER_PAGE,
                capped=body.total > len(items),
            ),
        )

    async def _closest_models(self, source: str, model: str) -> str:
        """`; closest models: A, B, C` so the agent can correct a name in one step."""
        try:
            batch = await self.fleet.list_models(source, None, 0)
        except FleetApiError:
            return ""
        names = [item.model for item in batch.items]
        close = difflib.get_close_matches(model.upper(), names, n=3, cutoff=0.4)
        return f"; closest models: {', '.join(close)}" if close else ""

    def specs(self) -> tuple[ToolSpec, ...]:
        """Tool specs with fleet-api failures mapped to structured tool errors."""

        def wrap(method: Any) -> Any:
            async def handler(args: dict[str, Any]) -> ToolOutput:
                try:
                    output: ToolOutput = await method(args)
                except FleetApiError as exc:
                    message = exc.message
                    if exc.code == "not_found" and "model" in args:
                        message += await self._closest_models(args["source"], args["model"])
                    raise ToolError(exc.code, message) from exc
                return output

            return handler

        return tuple(ToolSpec(name, wrap(getattr(self, name))) for name in TOOL_NAMES)


def build_runner(
    fleet: FleetApiClient | None = None, contracts_base: Path | None = None
) -> ToolRunner:
    """Transport-free runner. ``fleet`` defaults to a client for ``$FLEET_API_URL``."""
    return ToolRunner(SERVER, FleetTools(fleet or FleetApiClient()).specs(), contracts_base)


def build_server(
    fleet: FleetApiClient | None = None, contracts_base: Path | None = None
) -> Server[Any]:
    """The MCP server. Pass it to ``mcp.Client(server)`` for an in-memory session.

    Raises:
        ManifestMismatchError: a pinned description or schema hash does not match (FR-TOOL-5).
    """
    return build_mcp_server(
        build_runner(fleet, contracts_base), name=SERVER_NAME, version=__version__
    )
