"""Record -> replay round trip: CI runs investigations without a live model (ERS §3)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from agent_support import QUESTION, make_investigator, single_script
from cohortex_agent.llm.base import LLMRequest, RecordingMissing, request_key
from cohortex_agent.llm.recording import RecordingProvider, ReplayProvider
from cohortex_agent.llm.scripted import text
from cohortex_agent.schemas import Scope

pytestmark = pytest.mark.asyncio


def normalize(report: dict[str, Any]) -> str:
    """Evidence IDs depend on the investigation ID; replace them by order of appearance."""
    raw = json.dumps(report, sort_keys=True)
    seen: dict[str, str] = {}
    return re.sub(r"ev_[0-9a-f]{16}", lambda m: seen.setdefault(m.group(0), f"ev#{len(seen)}"), raw)


async def test_record_then_replay_reproduces_the_investigation(
    database_url: str, tmp_path: Path
) -> None:
    recorder = RecordingProvider(single_script(), tmp_path / "agent-service.jsonl")
    recorded = await make_investigator(database_url, recorder).run_investigation(
        QUESTION, Scope(source="backblaze")
    )
    assert recorded.status == "completed"
    assert recorded.report is not None

    lines = (tmp_path / "agent-service.jsonl").read_text().splitlines()
    assert len(lines) == 5  # guard, 3 agent turns, drafter
    for line in lines:
        record = json.loads(line)
        assert set(record) == {"key", "node", "recorded_at", "request", "response"}
        assert set(record["request"]) == {
            "model",
            "messages",
            "tools",
            "response_format",
            "temperature",
        }
        assert set(record["response"]) == {"text", "tool_calls", "usage", "model"}
        request = LLMRequest(
            messages=record["request"]["messages"],
            tools=record["request"]["tools"],
            response_format=record["request"]["response_format"],
            temperature=record["request"]["temperature"],
        )
        assert record["key"] == request_key("scripted-model", request)
    assert [json.loads(line)["node"] for line in lines] == [
        "guard",
        "agent",
        "agent",
        "agent",
        "drafter",
    ]

    replay = ReplayProvider("scripted-model", tmp_path)
    replayed = await make_investigator(database_url, replay).run_investigation(
        QUESTION, Scope(source="backblaze")
    )
    assert replayed.status == "completed", replayed.error
    assert replayed.report is not None
    assert replayed.investigation_id != recorded.investigation_id
    assert normalize(replayed.report.model_dump(mode="json")) == normalize(
        recorded.report.model_dump(mode="json")
    )


async def test_unknown_request_raises_recording_missing(tmp_path: Path) -> None:
    replay = ReplayProvider("scripted-model", tmp_path)
    with pytest.raises(RecordingMissing) as info:
        await replay.complete(LLMRequest(messages=[{"role": "user", "content": "new"}], node="x"))
    assert info.value.node == "x"


async def test_replay_of_an_unrecorded_question_fails_cleanly(
    database_url: str, tmp_path: Path
) -> None:
    outcome = await make_investigator(
        database_url, ReplayProvider("scripted-model", tmp_path)
    ).run_investigation("A question nobody recorded about ST4000DM000 AFR?")
    assert outcome.status == "failed"
    assert outcome.error is not None
    assert "no recorded response" in outcome.error


async def test_repeated_identical_requests_replay_in_recorded_order(tmp_path: Path) -> None:
    from cohortex_agent.llm.scripted import ScriptedProvider

    request = LLMRequest(messages=[{"role": "user", "content": "same"}], node="n")
    recorder = RecordingProvider(
        ScriptedProvider({"n": [text("first"), text("second")]}), tmp_path / "r.jsonl"
    )
    await recorder.complete(request)
    await recorder.complete(request)
    replay = ReplayProvider("scripted-model", tmp_path)
    assert len(replay) == 2
    assert [(await replay.complete(request)).text for _ in range(3)] == [
        "first",
        "second",
        "second",
    ]
