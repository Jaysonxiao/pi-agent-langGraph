"""Conditional routing for the minimal graph."""

from typing import Literal, cast

from langgraph.graph import END
from langgraph.runtime import Runtime

from pi_agent.domain.state import AgentState
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.context import RunContext


def route_after_model(state: AgentState) -> Literal["__end__"]:
    """End only after the model node produced an explicit terminal status."""
    if state["status"] not in {"completed", "failed"}:
        raise ValueError("Model node must set a terminal status before routing.")
    return cast(Literal["__end__"], END)


def route_after_tool_model(
    state: AgentState, runtime: Runtime[RunContext | AsyncRunContext]
) -> Literal["tools", "tool_limit", "__end__"]:
    """Route a completed model update to tools, the loop guard, or END."""
    if state["status"] in {"completed", "failed"}:
        return cast(Literal["__end__"], END)
    if state["status"] != "awaiting_tools":
        raise ValueError("Model node must complete, fail, or request tools before routing.")
    if state["tool_rounds"] >= runtime.context.max_tool_rounds:
        return "tool_limit"
    return "tools"
