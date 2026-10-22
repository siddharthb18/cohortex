"""LangGraph graphs for both modes behind one builder (ADR-006)."""

from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from cohortex_agent.graphs.context import RunContext
from cohortex_agent.graphs.orchestrated import build_orchestrated_graph
from cohortex_agent.graphs.single import build_single_graph


def build_graph(ctx: RunContext) -> CompiledStateGraph[Any, Any, Any, Any]:
    if ctx.mode == "orchestrated":
        return build_orchestrated_graph(ctx)
    return build_single_graph(ctx)


__all__ = ["RunContext", "build_graph"]
