"""Model and tool nodes for the M2/M3 graphs."""

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.runtime import Runtime

from pi_agent.context.runtime import prepare_model_messages
from pi_agent.domain.state import AgentState, AgentStateUpdate
from pi_agent.graph.context import RunContext
from pi_agent.tools.registry import create_error_tool_message


def model_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentStateUpdate:
    """Call the model and return only the state fields changed by this node."""
    try:
        model_messages = prepare_model_messages(
            state["messages"],
            runtime.context.context_config,
        )
    except Exception as exc:
        return {
            "status": "failed",
            "error": {
                "code": "context_error",
                "exception_type": type(exc).__name__,
                "message": "Context preparation failed; original messages are preserved.",
            },
        }
    try:
        reply = runtime.context.model.invoke(model_messages)
    except Exception as exc:
        return {
            "status": "failed",
            "error": {
                "code": "model_error",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        }

    return {
        "messages": [reply],
        "status": "awaiting_tools" if reply.tool_calls else "completed",
        "error": None,
    }


def tool_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentStateUpdate:
    """Execute requested tools sequentially and return result-message deltas."""
    assistant_message = _latest_tool_request(state)
    results: list[AnyMessage] = [
        runtime.context.tools.execute_call(call) for call in assistant_message.tool_calls
    ]
    return {
        "messages": results,
        "status": "ready",
        "error": None,
        "tool_rounds": state["tool_rounds"] + 1,
    }


def tool_limit_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentStateUpdate:
    """Return correlated errors instead of executing calls beyond the round limit."""
    assistant_message = _latest_tool_request(state)
    maximum = runtime.context.max_tool_rounds
    results: list[AnyMessage] = [
        create_error_tool_message(
            call,
            code="tool_round_limit",
            message=f"Tool round limit reached ({maximum}); call was not executed.",
        )
        for call in assistant_message.tool_calls
    ]
    return {
        "messages": results,
        "status": "failed",
        "error": {
            "code": "tool_round_limit",
            "max_rounds": maximum,
            "message": f"Tool round limit reached ({maximum}).",
        },
    }


def _latest_tool_request(state: AgentState) -> AIMessage:
    """Return the latest assistant message after checking graph invariants."""
    if not state["messages"]:
        raise ValueError("Tool routing requires at least one message.")

    message = state["messages"][-1]
    if not isinstance(message, AIMessage) or not message.tool_calls:
        raise ValueError("Tool routing requires an AIMessage with tool calls.")
    return message
