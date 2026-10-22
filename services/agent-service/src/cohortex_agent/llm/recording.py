"""Record and replay LLM traffic so CI never calls a live model (ERS §3, CLAUDE.md).

Recording format: JSON Lines, one object per LLM call, appended to
`$COHORTEX_RECORDINGS_DIR/$COHORTEX_RECORDINGS_FILE`:

    {"key": "<sha256 hex>",                      # implementation-notes §7 request hash
     "node": "drafter",                          # graph node (informational)
     "recorded_at": "2026-10-21T18:00:00+00:00",
     "request": {"model", "messages", "tools", "response_format", "temperature"},
     "response": {"text", "tool_calls": [{"id", "name", "arguments"}],
                  "usage": {"input_tokens", "output_tokens"}, "model"}}

Replay loads every `*.jsonl` file under the directory (recursively). When one key was recorded
more than once, the responses are served in recorded order and the last one repeats.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cohortex_agent.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    RecordingMissing,
    canonical_json,
    request_key,
)


class RecordingProvider:
    """Wraps a live provider and appends each request/response pair to a JSONL file."""

    def __init__(self, inner: LLMProvider, path: Path) -> None:
        self._inner = inner
        self._path = path
        self._lock = asyncio.Lock()

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await self._inner.complete(request)
        record: dict[str, Any] = {
            "key": request_key(self.model_id, request),
            "node": request.node,
            "recorded_at": datetime.now(UTC).isoformat(),
            "request": {
                "model": self.model_id,
                "messages": request.messages,
                "tools": request.tools,
                "response_format": request.response_format,
                "temperature": request.temperature,
            },
            "response": response.to_dict(),
        }
        line = canonical_json(record) + "\n"
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        return response


class ReplayProvider:
    """Serves recorded responses by request hash; unknown requests raise `RecordingMissing`."""

    def __init__(self, model_id: str, directory: Path) -> None:
        self._model = model_id
        self._responses: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._served: dict[str, int] = defaultdict(int)
        if directory.is_dir():
            for path in sorted(directory.rglob("*.jsonl")):
                self._load(path)

    def _load(self, path: Path) -> None:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if isinstance(record, dict) and "key" in record and "response" in record:
                    self._responses[str(record["key"])].append(record["response"])

    @property
    def model_id(self) -> str:
        return self._model

    def __len__(self) -> int:
        return sum(len(v) for v in self._responses.values())

    async def complete(self, request: LLMRequest) -> LLMResponse:
        key = request_key(self._model, request)
        recorded = self._responses.get(key)
        if not recorded:
            raise RecordingMissing(key, request.node)
        index = min(self._served[key], len(recorded) - 1)
        self._served[key] += 1
        return LLMResponse.from_dict(recorded[index])
