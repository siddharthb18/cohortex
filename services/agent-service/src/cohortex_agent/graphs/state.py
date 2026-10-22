"""LangGraph state. Plain JSON-able data; dependencies live in `RunContext`.

It carries the fields of contracts §6 `InvestigationState` that change during a run (plan, draft,
revisions, status); counters live in `Budget` because parallel workers share them.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class GraphState(TypedDict, total=False):
    status: str  # running | completed | refused | budget_exceeded
    refusal_reason: str
    # single mode: the tool-calling conversation
    messages: list[dict[str, Any]]
    agent_turns: int
    gathering_done: bool
    # orchestrated mode
    plan: dict[str, Any]
    done_tasks: Annotated[list[str], operator.add]
    # both modes: what gatherers report to the drafter, keyed by source (agent or task id)
    notes: Annotated[list[dict[str, Any]], operator.add]
    # drafting and checking
    draft_text: str
    draft: dict[str, Any]
    unsupported_notes: list[str]
    revisions: int
    report: dict[str, Any]


class WorkerInput(TypedDict):
    task: dict[str, Any]
    dependency_notes: list[dict[str, Any]]
