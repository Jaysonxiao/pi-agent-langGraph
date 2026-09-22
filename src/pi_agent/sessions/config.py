"""Stable mapping between application session IDs and LangGraph thread config."""

from langchain_core.runnables import RunnableConfig

MAX_THREAD_ID_LENGTH = 255


def session_config(session_id: str) -> RunnableConfig:
    """Validate an application session ID and map it to a checkpoint thread."""
    if not session_id or session_id != session_id.strip():
        raise ValueError("Session id must be a non-empty string without surrounding whitespace.")
    if len(session_id) > MAX_THREAD_ID_LENGTH:
        raise ValueError(f"Session id must not exceed {MAX_THREAD_ID_LENGTH} characters.")

    return {"configurable": {"thread_id": session_id}}


def checkpoint_config(session_id: str, checkpoint_id: str) -> RunnableConfig:
    """Address one checkpoint within a validated session thread."""
    session_config(session_id)
    if not checkpoint_id or checkpoint_id != checkpoint_id.strip():
        raise ValueError("Checkpoint id must be a non-empty string without surrounding whitespace.")

    return {
        "configurable": {
            "thread_id": session_id,
            "checkpoint_id": checkpoint_id,
        }
    }
