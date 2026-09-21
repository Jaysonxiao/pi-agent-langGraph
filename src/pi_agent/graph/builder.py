"""Builder for the M2 user-to-model graph."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from pi_agent.domain.state import AgentState
from pi_agent.graph.context import RunContext
from pi_agent.graph.nodes import model_node, tool_limit_node, tool_node
from pi_agent.graph.routing import route_after_model, route_after_tool_model

MODEL_NODE = "model"
TOOLS_NODE = "tools"
TOOL_LIMIT_NODE = "tool_limit"


def build_minimal_graph() -> CompiledStateGraph[AgentState, RunContext, AgentState, AgentState]:
    """Compile a single-node graph with an explicit conditional end."""
    builder = StateGraph(AgentState, context_schema=RunContext)
    builder.add_node(MODEL_NODE, model_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_model)
    return builder.compile()


def build_tool_graph() -> CompiledStateGraph[AgentState, RunContext, AgentState, AgentState]:
    """Compile the M3 model/tool loop with an explicit round-limit terminal path."""
    builder = StateGraph(AgentState, context_schema=RunContext)
    builder.add_node(MODEL_NODE, model_node)
    builder.add_node(TOOLS_NODE, tool_node)
    builder.add_node(TOOL_LIMIT_NODE, tool_limit_node)
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, route_after_tool_model)
    builder.add_edge(TOOLS_NODE, MODEL_NODE)
    builder.add_edge(TOOL_LIMIT_NODE, END)
    return builder.compile()
