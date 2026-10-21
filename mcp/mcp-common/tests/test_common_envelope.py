"""FR-TOOL-3 and FR-TOOL-6: envelope shape, 4 KB cap and lossless paging."""

from typing import Any

import pytest
from cohortex_mcp_common.envelope import (
    SIZE_CAP_BYTES,
    Paging,
    ToolOutput,
    byte_size,
    finalize,
)
from cohortex_mcp_common.errors import ToolError
from cohortex_mcp_common.testing import assert_envelope

ROWS = [{"model": f"MODEL-{i:04d}", "drive_count": i * 7, "media": "hdd"} for i in range(300)]


def _page(page: int, rows: list[dict[str, Any]], **paging: Any) -> dict[str, Any]:
    output = ToolOutput(
        source="test",
        data={"items": rows, "generated_at": "2026-10-02T16:20:11Z"},
        paging=Paging("items", **paging),
    )
    return finalize("fleet.list_models", {"source": "backblaze", "page": page}, output)


def test_non_paged_result_is_wrapped() -> None:
    env = finalize("stats.afr_ci", {"failures": 1}, ToolOutput("mcp-stats afr_ci", {"x": 1}))
    assert_envelope(env)
    assert env["evidence_id"] == ""
    assert env["tool"] == "stats.afr_ci"
    assert env["truncated"] is False
    assert env["next_page"] is None


def test_oversized_non_paged_result_is_too_large() -> None:
    with pytest.raises(ToolError) as info:
        finalize("stats.afr_ci", {}, ToolOutput("s", {"blob": "x" * SIZE_CAP_BYTES}))
    assert info.value.code == "too_large"


def test_pages_cover_every_row_once_and_fit_4kb() -> None:
    collected: list[dict[str, Any]] = []
    page: int | None = 0
    pages = 0
    while page is not None:
        env = _page(page, ROWS)
        assert_envelope(env)
        assert byte_size(env) <= SIZE_CAP_BYTES
        collected.extend(env["data"]["items"])
        assert env["truncated"] is (env["next_page"] is not None)
        page = env["next_page"]
        pages += 1
    assert collected == ROWS
    assert pages > 1


def test_split_does_not_depend_on_page_number_or_timestamp() -> None:
    first = _page(1, ROWS)
    output = ToolOutput(
        source="test",
        data={"items": ROWS, "generated_at": "2026-10-02T16:20:11.123456+00:00"},
        paging=Paging("items"),
    )
    again = finalize("fleet.list_models", {"source": "backblaze", "page": 1}, output)
    assert first["data"]["items"] == again["data"]["items"]


def test_row_limit_per_page_and_capped_flag() -> None:
    env = _page(0, ROWS[:5], max_rows_per_page=2, capped=True)
    assert len(env["data"]["items"]) == 2
    last = _page(2, ROWS[:5], max_rows_per_page=2, capped=True)
    assert last["next_page"] is None
    assert last["truncated"] is True  # the tool's row limit removed rows


def test_empty_list_is_one_page_and_past_end_is_invalid() -> None:
    env = _page(0, [])
    assert env["data"]["items"] == []
    assert env["next_page"] is None
    with pytest.raises(ToolError) as info:
        _page(1, [])
    assert info.value.code == "invalid_argument"


def test_data_as_bare_list() -> None:
    env = finalize(
        "fleet.list_models",
        {"source": "backblaze", "page": 0},
        ToolOutput("s", ROWS, Paging(None)),
    )
    assert isinstance(env["data"], list)
    assert byte_size(env) <= SIZE_CAP_BYTES


def test_row_bigger_than_cap_is_too_large() -> None:
    with pytest.raises(ToolError) as info:
        _page(0, [{"blob": "x" * SIZE_CAP_BYTES}])
    assert info.value.code == "too_large"


def test_non_finite_numbers_become_structured_error() -> None:
    with pytest.raises(ToolError) as info:
        finalize("stats.afr_ci", {}, ToolOutput("s", {"x": float("inf")}))
    assert info.value.code == "upstream_error"
