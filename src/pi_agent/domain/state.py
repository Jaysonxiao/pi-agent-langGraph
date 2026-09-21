"""Typed state contracts shared by the model and tool-loop graphs."""

from typing import Annotated, Literal, TypeAlias, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.message import add_messages

RunStatus = Literal["ready", "awaiting_tools", "completed", "failed"]


class ModelError(TypedDict):
    """Stable, serializable details for a failed model call."""

    code: Literal["model_error"]
    exception_type: str
    message: str


class ToolLoopError(TypedDict):
    """Stable terminal details when the tool loop reaches its configured limit."""

    code: Literal["tool_round_limit"]
    max_rounds: int
    message: str


AgentError: TypeAlias = ModelError | ToolLoopError


class AgentState(TypedDict):
    """Complete shared state for one minimal graph run."""

    messages: Annotated[list[AnyMessage], add_messages]
    status: RunStatus
    error: AgentError | None
    tool_rounds: int


class AgentStateUpdate(TypedDict, total=False):
    """Partial update returned by a graph node."""

    messages: list[AnyMessage]
    status: RunStatus
    error: AgentError | None
    tool_rounds: int


def create_initial_state(content: str, *, message_id: str = "user-1") -> AgentState:
    """Create validated graph input while preserving the user's original text."""
    if not content.strip():
        raise ValueError("User message must not be blank.")
    if not message_id:
        raise ValueError("Message id must not be empty.")

    return {
        "messages": [HumanMessage(content=content, id=message_id)],
        "status": "ready",
        "error": None,
        "tool_rounds": 0,
    }
