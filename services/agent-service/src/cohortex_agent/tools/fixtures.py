"""Test hook for the eval harness: serve fixed tool outputs from JSON files.

Off by default. When `COHORTEX_TOOL_FIXTURES_DIR` is set (and `COHORTEX_ENV` is not `demo`),
a call to `<server>.<name>` first looks for `<dir>/<server>.<name>.json` (for example
`fleet.cohort_afr.json`). If the file exists, its content is returned instead of calling MCP:

- an envelope (an object with `tool` and `data`) is returned as is, with `args` set to the call's
  arguments and `evidence_id` left for the ledger;
- `{"error": {"code", "message"}}` is raised as a tool error;
- anything else is treated as the envelope's `data`.

Files are read on every call, so the harness can swap them between cases (e.g. a poisoned tool
output for adversarial case `adv-0001`). Tools without a file go to the real gateway.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cohortex_agent.tools.base import ToolCallError, ToolGateway, ToolSpec


class FixtureOverlayGateway:
    def __init__(self, inner: ToolGateway, directory: Path) -> None:
        self._inner = inner
        self._dir = directory

    async def list_tools(self) -> list[ToolSpec]:
        return await self._inner.list_tools()

    async def call(self, server: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = f"{server}.{name}"
        path = self._dir / f"{tool}.json"
        if not path.is_file():
            return await self._inner.call(server, name, args)
        content = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(content, dict) and isinstance(content.get("error"), dict):
            error = content["error"]
            raise ToolCallError(str(error.get("code", "upstream_error")), str(error.get("message")))
        if isinstance(content, dict) and "tool" in content and "data" in content:
            envelope = dict(content)
        else:
            envelope = {
                "tool": tool,
                "source": f"fixture {path.name}",
                "generated_at": datetime.now(UTC).isoformat(),
                "data": content,
            }
        envelope.update(evidence_id="", args=args)
        envelope.setdefault("truncated", False)
        envelope.setdefault("next_page", None)
        return envelope
