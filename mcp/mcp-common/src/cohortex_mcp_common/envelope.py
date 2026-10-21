"""Evidence envelope and the 4 KB result cap (contracts §5, FR-TOOL-3, FR-TOOL-6).

Every tool result is::

    {"evidence_id": "", "tool": "fleet.cohort_afr", "args": {...}, "source": "...",
     "generated_at": "2026-10-02T16:20:11Z", "data": ..., "truncated": false, "next_page": null}

``evidence_id`` is empty here; agent-service's evidence ledger fills it when it records the call.

Paging is lossless. A list tool first builds its complete, bounded row list (for example at most
100 models). The rows are then split, in order, into consecutive pages that each keep the whole
serialized envelope within 4 KB (and within an optional per-page row limit). ``page`` picks one;
``next_page`` names the following one, or is null on the last page. The split depends only on the
rows and the arguments other than ``page``, so the same query always pages the same way.
``truncated`` is true when this result is not the whole answer: more pages follow, or the tool's
row limit cut the list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from cohortex_mcp_common.errors import ToolError

SIZE_CAP_BYTES = 4096
PAGE_MAX = 999
"""Upper bound of every ``page`` argument (schemas say ``maximum: 999``)."""

_SIZING_TIMESTAMP = "X" * 40


def serialize(value: Any) -> str:
    """Compact JSON, exactly as measured for the cap and sent as the text content."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def byte_size(value: Any) -> int:
    """Serialized size in UTF-8 bytes."""
    return len(serialize(value).encode("utf-8"))


def utc_now() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Paging:
    """How a tool's ``data`` is paged.

    Attributes:
        list_key: key in ``data`` holding the row list; ``None`` when ``data`` itself is the list.
        max_rows_per_page: optional row limit per page on top of the byte cap.
        capped: true when the tool's row limit already removed rows (sets ``truncated``).
    """

    list_key: str | None
    max_rows_per_page: int | None = None
    capped: bool = False


@dataclass(frozen=True)
class ToolOutput:
    """What a tool handler returns before it is wrapped in the envelope."""

    source: str
    data: Any
    paging: Paging | None = None


def make_envelope(
    tool: str,
    args: dict[str, Any],
    source: str,
    data: Any,
    *,
    generated_at: str,
    truncated: bool = False,
    next_page: int | None = None,
) -> dict[str, Any]:
    """Build the envelope dict (field order matches contracts §5)."""
    return {
        "evidence_id": "",
        "tool": tool,
        "args": args,
        "source": source,
        "generated_at": generated_at,
        "data": data,
        "truncated": truncated,
        "next_page": next_page,
    }


def _rows_of(data: Any, list_key: str | None) -> list[Any]:
    rows = data if list_key is None else (data.get(list_key) if isinstance(data, dict) else None)
    if not isinstance(rows, list):
        raise ToolError("upstream_error", "result rows are missing or not a list")
    return rows


def _with_rows(data: Any, list_key: str | None, rows: list[Any]) -> Any:
    if list_key is None:
        return rows
    replaced = dict(cast(dict[str, Any], data))
    replaced[list_key] = rows
    return replaced


def _split_pages(rows: list[Any], budget: int, max_rows: int | None) -> list[list[Any]]:
    pages: list[list[Any]] = []
    current: list[Any] = []
    used = 0
    for row in rows:
        size = byte_size(row)
        if size > budget:
            raise ToolError("too_large", "a single result row exceeds the 4 KB result cap")
        extra = size + (1 if current else 0)  # comma between rows
        if current and (
            used + extra > budget or (max_rows is not None and len(current) >= max_rows)
        ):
            pages.append(current)
            current, used = [], 0
            extra = size
        current.append(row)
        used += extra
    if current or not pages:
        pages.append(current)
    return pages


def finalize(
    tool: str,
    args: dict[str, Any],
    output: ToolOutput,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Wrap ``output`` in the envelope, applying the 4 KB cap and paging.

    Raises:
        ToolError: ``too_large`` when a non-list result (or one row) cannot fit in 4 KB;
            ``invalid_argument`` when ``page`` is past the last page.
    """
    stamp = generated_at or utc_now()
    try:
        if output.paging is None:
            envelope = make_envelope(tool, args, output.source, output.data, generated_at=stamp)
            if byte_size(envelope) > SIZE_CAP_BYTES:
                raise ToolError("too_large", "the result exceeds the 4 KB result cap")
            return envelope

        paging = output.paging
        rows = _rows_of(output.data, paging.list_key)
        sizing_data = _with_rows(output.data, paging.list_key, [])
        if isinstance(sizing_data, dict) and "generated_at" in sizing_data:
            sizing_data["generated_at"] = _SIZING_TIMESTAMP
        sizing = make_envelope(
            tool,
            {**args, "page": PAGE_MAX},
            output.source,
            sizing_data,
            generated_at=_SIZING_TIMESTAMP,
            truncated=True,
            next_page=PAGE_MAX,
        )
        budget = SIZE_CAP_BYTES - byte_size(sizing)
        if budget <= 0:
            raise ToolError("too_large", "the result exceeds the 4 KB result cap")
        pages = _split_pages(rows, budget, paging.max_rows_per_page)
        page = int(args.get("page", 0))
        if page >= len(pages):
            raise ToolError(
                "invalid_argument", f"page {page} is past the last page ({len(pages) - 1})"
            )
        next_page = page + 1 if page + 1 < len(pages) else None
        envelope = make_envelope(
            tool,
            args,
            output.source,
            _with_rows(output.data, paging.list_key, pages[page]),
            generated_at=stamp,
            truncated=next_page is not None or paging.capped,
            next_page=next_page,
        )
        if byte_size(envelope) > SIZE_CAP_BYTES:  # only if a timestamp exceeded the reserve
            raise ToolError("too_large", "the result exceeds the 4 KB result cap")
        return envelope
    except ValueError as exc:  # allow_nan=False: NaN/Infinity cannot be sent as JSON
        raise ToolError("upstream_error", "the result contained a non-finite number") from exc
