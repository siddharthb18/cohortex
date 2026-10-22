"""Orchestrated mode (FR-AGT-3/4): planner -> workers (<= 3 in parallel) -> shared tail.

    START -> guard -> planner -> dispatch --Send x<=3--> worker --> dispatch ... -> drafter
             drafter -> checker -> (drafter, at most twice) -> reporter -> END

`dispatch` sends every task whose dependencies are done (at most 3 per superstep) to `worker`
with LangGraph's `Send`; workers of one superstep run concurrently. Each worker may only use the
tools of its task kind: data -> fleet, stats -> stats, literature -> docs.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send
from pydantic import model_validator

from cohortex_agent.graphs.context import RunContext, data_block
from cohortex_agent.graphs.nodes import (
    make_checker,
    make_drafter,
    make_guard,
    make_reporter,
    question_message,
    route_after_check,
    route_after_guard,
)
from cohortex_agent.graphs.state import GraphState, WorkerInput
from cohortex_agent.llm.base import Message
from cohortex_agent.schemas import Plan, Task

MAX_PARALLEL_WORKERS = 3
MAX_WORKER_TURNS = 8
KIND_SERVER = {"data": "fleet", "stats": "stats", "literature": "docs"}


class CheckedPlan(Plan):
    """`Plan` plus graph rules: unique task IDs, known dependencies, no cycles."""

    @model_validator(mode="after")
    def _graph_rules(self) -> CheckedPlan:
        ids = [t.id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task ids must be unique")
        known = set(ids)
        for task in self.tasks:
            unknown = [d for d in task.depends_on if d not in known]
            if unknown:
                raise ValueError(f"task {task.id} depends on unknown task(s) {unknown}")
            if task.id in task.depends_on:
                raise ValueError(f"task {task.id} depends on itself")
        done: set[str] = set()
        remaining = list(self.tasks)
        while remaining:
            ready = [t for t in remaining if set(t.depends_on) <= done]
            if not ready:
                raise ValueError("task dependencies contain a cycle")
            done |= {t.id for t in ready}
            remaining = [t for t in remaining if t.id not in done]
        return self


def build_orchestrated_graph(ctx: RunContext) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def planner(state: GraphState) -> dict[str, Any]:
        kinds = {
            kind: [f"{s.llm_name}: {s.description}" for s in ctx.tool_specs if s.server == server]
            for kind, server in KIND_SERVER.items()
        }
        available = {kind: tools for kind, tools in kinds.items() if tools}
        messages: list[Message] = [
            {"role": "system", "content": ctx.prompts.text("planner")},
            question_message(ctx, data_block("available_task_kinds_and_tools", available)),
        ]
        checked, _ = await ctx.structured("planner", messages, CheckedPlan)
        plan = Plan.model_validate(checked.model_dump())
        await ctx.ledger.step("planner", "plan", {"plan": plan.model_dump(mode="json")})
        return {"plan": plan.model_dump(mode="json")}

    async def dispatch(state: GraphState) -> dict[str, Any]:
        return {}

    def route_dispatch(state: GraphState) -> list[Send] | str:
        if ctx.budget.tool_limit_hit:
            return "drafter"
        plan = Plan.model_validate(state["plan"])
        done = set(state.get("done_tasks", []))
        ready = [t for t in plan.tasks if t.id not in done and set(t.depends_on) <= done]
        if not ready:
            return "drafter"
        notes = state.get("notes", [])
        return [
            Send(
                "worker",
                {
                    "task": task.model_dump(mode="json"),
                    "dependency_notes": [n for n in notes if n.get("source") in task.depends_on],
                },
            )
            for task in ready[:MAX_PARALLEL_WORKERS]
        ]

    async def worker(state: WorkerInput) -> dict[str, Any]:
        inp = state
        task = Task.model_validate(inp["task"])
        node = f"worker:{task.kind}"
        server = KIND_SERVER[task.kind]
        tools = [s for s in ctx.tool_specs if s.server == server]
        text = ""
        if not tools:
            text = f"No {server} tools are available, so this {task.kind} task was skipped."
        else:
            material: dict[str, Any] = {"task": task.model_dump(mode="json")}
            if inp["dependency_notes"]:
                material["notes_from_dependencies"] = inp["dependency_notes"]
            messages: list[Message] = [
                {"role": "system", "content": ctx.prompts.text("worker")},
                question_message(ctx, data_block("task", material)),
            ]
            for _ in range(MAX_WORKER_TURNS):
                response = await ctx.llm(node, messages, tools=tools)
                messages.append(response.assistant_message())
                if not response.tool_calls:
                    text = response.text or ""
                    break
                tool_messages, stopped = await ctx.run_tool_calls(
                    node, response.tool_calls, tools, alias_prefix=task.id
                )
                messages.extend(tool_messages)
                if stopped:
                    text = "Gathering stopped at the tool-call budget."
                    break
        return {
            "done_tasks": [task.id],
            "notes": [{"source": task.id, "kind": task.kind, "goal": task.goal, "text": text}],
        }

    graph = StateGraph(GraphState)
    graph.add_node("guard", make_guard(ctx))
    graph.add_node("planner", planner)
    graph.add_node("dispatch", dispatch)
    graph.add_node("worker", worker, input_schema=WorkerInput)
    graph.add_node("drafter", make_drafter(ctx))
    graph.add_node("checker", make_checker(ctx))
    graph.add_node("reporter", make_reporter(ctx))
    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", route_after_guard("planner"), ["planner", "reporter"])
    graph.add_edge("planner", "dispatch")
    graph.add_conditional_edges("dispatch", route_dispatch, ["worker", "drafter"])
    graph.add_edge("worker", "dispatch")
    graph.add_edge("drafter", "checker")
    graph.add_conditional_edges("checker", route_after_check, ["drafter", "reporter"])
    graph.add_edge("reporter", END)
    return graph.compile()
