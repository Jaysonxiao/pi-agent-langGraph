"""Builder for the M2 user-to-model graph."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pi_agent.domain.state import AgentState, AgentTurnInput
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.async_nodes import async_model_node, async_tool_limit_node, async_tool_node
from pi_agent.graph.context import RunContext
from pi_agent.graph.nodes import model_node, tool_limit_node, tool_node
from pi_agent.graph.routing import route_after_model, route_after_tool_model

MODEL_NODE = "model"
TOOLS_NODE = "tools"
TOOL_LIMIT_NODE = "tool_limit"


AgentGraph = CompiledStateGraph[AgentState, RunContext, AgentTurnInput, AgentState]
AsyncAgentGraph = CompiledStateGraph[AgentState, AsyncRunContext, AgentTurnInput, AgentState]


def build_minimal_graph(checkpointer: BaseCheckpointSaver[str] | None = None) -> AgentGraph:
    """Compile a single-node graph with an explicit conditional end."""
    builder = StateGraph(AgentState, context_schema=RunContext, input_schema=AgentTurnInput)
    builder.add_node(MODEL_NODE, model_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_model)
    return builder.compile(checkpointer=checkpointer)


def build_async_minimal_graph(
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> AsyncAgentGraph:
    """Compile the native async M8.5 graph without wrapping sync calls in threads."""
    builder = StateGraph(AgentState, context_schema=AsyncRunContext, input_schema=AgentTurnInput)
    builder.add_node(MODEL_NODE, async_model_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_model)
    return builder.compile(checkpointer=checkpointer)


def build_tool_graph(checkpointer: BaseCheckpointSaver[str] | None = None) -> AgentGraph:
    """Compile the M3 model/tool loop with an explicit round-limit terminal path."""
    builder = StateGraph(AgentState, context_schema=RunContext, input_schema=AgentTurnInput)
    builder.add_node(MODEL_NODE, model_node)
    builder.add_node(TOOLS_NODE, tool_node)
    builder.add_node(TOOL_LIMIT_NODE, tool_limit_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_tool_model)
    builder.add_edge(TOOLS_NODE, MODEL_NODE)
    builder.add_edge(TOOL_LIMIT_NODE, END)
    return builder.compile(checkpointer=checkpointer)


def build_async_tool_graph(
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> AsyncAgentGraph:
    """Compile the native async model/tool loop with an explicit round-limit path."""
    builder = StateGraph(AgentState, context_schema=AsyncRunContext, input_schema=AgentTurnInput)
    builder.add_node(MODEL_NODE, async_model_node)
    builder.add_node(TOOLS_NODE, async_tool_node)
    builder.add_node(TOOL_LIMIT_NODE, async_tool_limit_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_tool_model)
    builder.add_edge(TOOLS_NODE, MODEL_NODE)
    builder.add_edge(TOOL_LIMIT_NODE, END)
    return builder.compile(checkpointer=checkpointer)
