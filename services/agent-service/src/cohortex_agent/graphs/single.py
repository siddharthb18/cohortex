"""Single-agent mode (FR-AGT-2): one tool-calling loop over all tools, then the shared tail.

START -> guard -> agent <-> tools
                    |
                    v
                 drafter -> checker -> (drafter, at most twice) -> reporter -> END
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cohortex_agent.graphs.context import RunContext
from cohortex_agent.graphs.nodes import (
    make_checker,
    make_drafter,
    make_guard,
    make_reporter,
    question_message,
    route_after_check,
    route_after_guard,
)
from cohortex_agent.graphs.state import GraphState
from cohortex_agent.llm.base import Message, ToolCall

EXTRA_TURNS = 5  # model turns allowed beyond the tool-call budget before gathering is cut off


def _calls_from(message: Message) -> list[ToolCall]:
    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        calls.append(
            ToolCall(
                id=str(raw.get("id")),
                name=str(function.get("name")),
                arguments=str(function.get("arguments") or "{}"),
            )
        )
    return calls


def build_single_graph(ctx: RunContext) -> CompiledStateGraph[Any, Any, Any, Any]:
    max_turns = ctx.budget.max_tool_calls + EXTRA_TURNS

    async def agent(state: GraphState) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        if not messages:
            messages = [
                {"role": "system", "content": ctx.prompts.text("agent")},
                question_message(ctx),
            ]
        turns = state.get("agent_turns", 0)
        if turns >= max_turns:
            return {"gathering_done": True, "notes": [{"source": "agent", "text": ""}]}
        response = await ctx.llm("agent", messages, tools=ctx.tool_specs)
        messages.append(response.assistant_message())
        if response.tool_calls:
            return {"messages": messages, "agent_turns": turns + 1, "gathering_done": False}
        return {
            "messages": messages,
            "agent_turns": turns + 1,
            "gathering_done": True,
            "notes": [{"source": "agent", "text": response.text or ""}],
        }

    async def tools(state: GraphState) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        tool_messages, stopped = await ctx.run_tool_calls(
            "agent", _calls_from(messages[-1]), ctx.tool_specs
        )
        update: dict[str, Any] = {"messages": messages + tool_messages}
        if stopped:
            update["gathering_done"] = True
            update["notes"] = [
                {"source": "agent", "text": "Gathering stopped at the tool-call budget."}
            ]
        return update

    def after_agent(state: GraphState) -> str:
        return "drafter" if state.get("gathering_done") else "tools"

    def after_tools(state: GraphState) -> str:
        return "drafter" if state.get("gathering_done") else "agent"

    graph = StateGraph(GraphState)
    graph.add_node("guard", make_guard(ctx))
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("drafter", make_drafter(ctx))
    graph.add_node("checker", make_checker(ctx))
    graph.add_node("reporter", make_reporter(ctx))
    graph.add_edge(START, "guard")
    graph.add_conditional_edges("guard", route_after_guard("agent"), ["agent", "reporter"])
    graph.add_conditional_edges("agent", after_agent, ["tools", "drafter"])
    graph.add_conditional_edges("tools", after_tools, ["agent", "drafter"])
    graph.add_edge("drafter", "checker")
    graph.add_conditional_edges("checker", route_after_check, ["drafter", "reporter"])
    graph.add_edge("reporter", END)
    return graph.compile()
