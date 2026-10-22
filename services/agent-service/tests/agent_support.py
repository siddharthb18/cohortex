"""Test support: settings, scripted scenarios over the fake fixture, SSE parsing.

Fixture values (see `cohortex_agent.tools.fake`): ST12000NM000J had 2 failures over 98,010
drive-days in 2026Q1 (AFR 0.7448%) and 9 failures over 98,189 drive-days in 2026Q2 (AFR 3.3456%).
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from cohortex_agent.config import Settings
from cohortex_agent.db import Database
from cohortex_agent.events import EventBus
from cohortex_agent.llm.base import LLMProvider, LLMRequest, LLMResponse
from cohortex_agent.llm.scripted import ScriptedProvider, text, tool_calls
from cohortex_agent.prompts import PromptStore
from cohortex_agent.runner import Investigator
from cohortex_agent.tools.base import ToolGateway
from cohortex_agent.tools.fake import FakeToolGateway

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_DIR = REPO_ROOT / "prompts"
REPORT_SCHEMA = REPO_ROOT / "contracts" / "report" / "report.schema.json"

MODEL = "ST12000NM000J"
H1 = {"source": "backblaze", "model": MODEL, "from": "2026-01-01", "to": "2026-06-30"}
RATES = {"failures_a": 9, "drive_days_a": 98189, "failures_b": 2, "drive_days_b": 98010}
QUESTION = "Did the failure rate of Backblaze ST12000NM000J change between Q1 and Q2 2026?"


def make_settings(database_url: str, **overrides: Any) -> Settings:
    base = Settings(
        database_url=database_url,
        llm_model="scripted-model",
        prompts_dir=PROMPTS_DIR,
        max_seconds=30.0,
        tools_backend="fake",
    )
    return replace(base, **overrides)


def make_investigator(
    database_url: str,
    provider: LLMProvider,
    gateway: ToolGateway | None = None,
    **overrides: Any,
) -> Investigator:
    settings = make_settings(database_url, **overrides)
    return Investigator(
        settings=settings,
        db=Database(database_url),
        provider=provider,
        gateway=gateway or FakeToolGateway(),
        prompts=PromptStore(PROMPTS_DIR),
        bus=EventBus(),
    )


def in_scope() -> LLMResponse:
    return text({"in_scope": True, "reason": ""})


def ref(value: float, unit: str, evidence_id: str, field: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "evidence_id": evidence_id, "field": field}


def claim(
    text_: str,
    numbers: list[dict[str, Any]] | None = None,
    evidence_ids: list[str] | None = None,
    passage_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "text": text_,
        "numbers": numbers or [],
        "evidence_ids": evidence_ids or [],
        "passage_ids": passage_ids or [],
    }


def afr_claim(alias: str = "E1") -> dict[str, Any]:
    return claim(
        "ST12000NM000J's AFR rose to 3.35% in Q2 2026 from 0.74% in Q1 2026.",
        [
            ref(3.3456, "pct", alias, "series[1].afr_pct"),
            ref(0.7448, "pct", alias, "series[0].afr_pct"),
        ],
        [alias],
    )


def failures_claim(alias: str = "E1") -> dict[str, Any]:
    return claim(
        "Q2 2026 had 9 failures over 98,189 drive-days.",
        [
            ref(9, "count", alias, "series[1].failures"),
            ref(98189, "drive_days", alias, "series[1].drive_days"),
        ],
        [alias],
    )


def ratio_claim(alias: str = "E2") -> dict[str, Any]:
    return claim(
        "The Q2/Q1 rate ratio was 4.49 with p = 0.0652, so the rise is not significant at 0.05.",
        [ref(4.4918, "ratio", alias, "rate_ratio"), ref(0.0652, "p_value", alias, "p_value")],
        [alias],
    )


def draft(
    *,
    summary: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
    hypotheses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "summary": summary or [],
        "findings": findings or [],
        "hypotheses": hypotheses or [],
        "recommended_actions": ["Check failed drives of ST12000NM000J for a shared batch."],
        "limitations": [],
    }


def good_draft(e1: str = "E1", e2: str = "E2") -> dict[str, Any]:
    return draft(
        summary=[afr_claim(e1)],
        findings=[afr_claim(e1), failures_claim(e1), ratio_claim(e2)],
        hypotheses=[
            {
                "statement": "A bad manufacturing batch entered service in Q2.",
                "support": [failures_claim(e1)],
                "confidence": "low",
                "how_to_confirm": "Group Q2 failures by first_seen date.",
            }
        ],
    )


def single_script(drafts: list[dict[str, Any]] | None = None) -> ScriptedProvider:
    """guard -> cohort_afr -> compare_rates -> notes -> drafter (one response per draft)."""
    return ScriptedProvider(
        {
            "guard": [in_scope()],
            "agent": [
                tool_calls(("fleet_cohort_afr", H1)),
                tool_calls(("stats_compare_rates", RATES)),
                text("E1 series[1].afr_pct is the Q2 AFR; E2 has the rate ratio."),
            ],
            "drafter": [text(d) for d in (drafts or [good_draft()])],
        }
    )


_FENCE = re.compile(r"<<<DATA.*?DATA>>>", re.DOTALL)


def instruction_text(request: LLMRequest) -> str:
    """What a naive model would read as instructions: system/user text outside data fences."""
    parts = []
    for message in request.messages:
        if message.get("role") in ("system", "user"):
            parts.append(_FENCE.sub("", str(message.get("content") or "")))
    return "\n".join(parts)


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in re.split(r"\r?\n\r?\n", body):
        name, data = "message", []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events
