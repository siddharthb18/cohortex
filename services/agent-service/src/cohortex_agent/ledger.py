"""Evidence ledger and step log (FR-AGT-5).

Every model-requested tool call, including rejected and failed ones, becomes one `evidence` row
and one `tool_call` step, so the ledger count always equals the tool-call count.

    evidence_id = "ev_" + sha256(f"{investigation_id}|{seq}|{tool}|{canonical_args}")[:16]

`seq` is the step sequence number of the `tool_call` step; `tool` is `<server>.<name>`;
`canonical_args` is the JSON of the arguments with sorted keys and no whitespace.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from cohortex_agent.db import Database, utcnow
from cohortex_agent.events import EventBus
from cohortex_agent.schemas import StepView


def canonical_args(args: dict[str, Any]) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_evidence_id(investigation_id: str, seq: int, tool: str, args: dict[str, Any]) -> str:
    material = f"{investigation_id}|{seq}|{tool}|{canonical_args(args)}"
    return "ev_" + hashlib.sha256(material.encode()).hexdigest()[:16]


def step_data(row: Mapping[str, Any]) -> dict[str, Any]:
    """A step as the SSE `step` event carries it, identical for live and replayed steps."""

    def utc(value: Any) -> Any:
        return value.astimezone(UTC) if isinstance(value, datetime) else value

    view = StepView.model_validate(
        {**row, "started_at": utc(row["started_at"]), "ended_at": utc(row.get("ended_at"))}
    )
    return view.model_dump(mode="json")


def _summary(envelope: dict[str, Any] | None, error: dict[str, Any] | None) -> str:
    if error is not None:
        return f"error {error.get('code')}: {str(error.get('message'))[:160]}"
    data = (envelope or {}).get("data")
    if isinstance(data, dict):
        for key in ("series", "items"):
            if isinstance(data.get(key), list):
                truncated = bool((envelope or {}).get("truncated"))
                return f"{len(data[key])} {key}" + (" (truncated)" if truncated else "")
        return f"{len(data)} fields"
    if isinstance(data, list):
        truncated = bool((envelope or {}).get("truncated"))
        return f"{len(data)} rows" + (" (truncated)" if truncated else "")
    return "ok"


class Ledger:
    """Allocates step numbers, writes steps and evidence, and publishes live events."""

    def __init__(self, db: Database, bus: EventBus, investigation_id: str) -> None:
        self._db = db
        self._bus = bus
        self.investigation_id = investigation_id
        self._seq = 0
        self._lock = asyncio.Lock()
        self.evidence: dict[str, dict[str, Any]] = {}  # evidence_id -> stored result
        self.order: list[str] = []

    async def step(
        self,
        node: str,
        kind: str,
        payload: dict[str, Any],
        started_at: datetime | None = None,
    ) -> int:
        async with self._lock:
            return await self._write_step(node, kind, payload, started_at or utcnow())

    async def _write_step(
        self, node: str, kind: str, payload: dict[str, Any], started_at: datetime
    ) -> int:
        self._seq += 1
        seq = self._seq
        ended_at = utcnow()
        await self._db.insert_step(
            self.investigation_id,
            seq=seq,
            node=node,
            kind=kind,
            payload=payload,
            started_at=started_at,
            ended_at=ended_at,
        )
        row = {
            "seq": seq,
            "node": node,
            "kind": kind,
            "payload": payload,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        self._bus.publish(self.investigation_id, {"event": "step", "data": step_data(row)})
        return seq

    async def record_tool_call(
        self,
        *,
        node: str,
        tool: str,
        args: dict[str, Any],
        envelope: dict[str, Any] | None,
        error: dict[str, Any] | None,
        started_at: datetime,
    ) -> tuple[str, dict[str, Any]]:
        """Store one call; returns (evidence_id, stored result with `evidence_id` filled)."""
        async with self._lock:
            seq = self._seq + 1
            evidence_id = make_evidence_id(self.investigation_id, seq, tool, args)
            if envelope is not None:
                result = {**envelope, "evidence_id": evidence_id}
            else:
                result = {"evidence_id": evidence_id, "tool": tool, "args": args, "error": error}
            await self._db.insert_evidence(
                evidence_id=evidence_id,
                investigation_id=self.investigation_id,
                tool_name=tool,
                args=args,
                result=result,
                created_at=utcnow(),
            )
            self.evidence[evidence_id] = result
            self.order.append(evidence_id)
            await self._write_step(
                node,
                "tool_call",
                {
                    "tool": tool,
                    "args": args,
                    "evidence_id": evidence_id,
                    "ok": error is None,
                    "summary": _summary(envelope, error),
                },
                started_at,
            )
            return evidence_id, result
