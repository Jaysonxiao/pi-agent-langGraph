"""Unit tests for the stable checkpoint-history projection."""

from typing import cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.types import StateSnapshot

from pi_agent.sessions import SessionCheckpoint, project_session_checkpoint


def test_project_session_checkpoint_exposes_only_stable_summary_fields() -> None:
    snapshot = StateSnapshot(
        values={
            "messages": [
                HumanMessage(content="hello", id="user-1"),
                AIMessage(content="hi", id="assistant-1"),
            ],
            "status": "completed",
            "error": None,
            "tool_rounds": 0,
        },
        next=(),
        config={
            "configurable": {
                "thread_id": "session-1",
                "checkpoint_ns": "",
                "checkpoint_id": "checkpoint-1",
            }
        },
        metadata=cast(
            CheckpointMetadata,
            {"source": "loop", "step": 1, "writes": {}},
        ),
        created_at="2026-09-21T10:00:00+00:00",
        parent_config=None,
        tasks=(),
        interrupts=(),
    )

    assert project_session_checkpoint(snapshot) == SessionCheckpoint(
        checkpoint_id="checkpoint-1",
        created_at="2026-09-21T10:00:00+00:00",
        source="loop",
        step=1,
        status="completed",
        message_count=2,
        next_nodes=(),
    )


def test_project_session_checkpoint_rejects_missing_checkpoint_id() -> None:
    snapshot = StateSnapshot(
        values={},
        next=("model",),
        config={"configurable": {"thread_id": "session-1"}},
        metadata=cast(
            CheckpointMetadata,
            {"source": "input", "step": -1, "writes": {}},
        ),
        created_at="2026-09-21T10:00:00+00:00",
        parent_config=None,
        tasks=(),
        interrupts=(),
    )

    with pytest.raises(ValueError, match="checkpoint_id"):
        project_session_checkpoint(snapshot)
