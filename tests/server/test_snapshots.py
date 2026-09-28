"""Remote snapshot projection exposes bounded display fields only."""

from collections.abc import Sequence
from typing import cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.types import StateSnapshot

from pi_agent.protocol.messages import MAX_DISPLAY_TEXT_BYTES, SessionSnapshot
from pi_agent.server.snapshots import MAX_SNAPSHOT_TEXT_BYTES, project_session_snapshot


def _state(
    messages: Sequence[object],
    *,
    next_nodes: tuple[str, ...] = (),
    checkpoint_id: str | None = "checkpoint-private",
    status: str = "completed",
) -> StateSnapshot:
    configurable: dict[str, str] = {"thread_id": "private-thread"}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return StateSnapshot(
        values={"messages": list(messages), "status": status, "error": None},
        next=next_nodes,
        config={
            "configurable": {
                **configurable,
                "api_key": "must-not-leak",
            }
        },
        metadata=cast(CheckpointMetadata, {"source": "loop", "step": 7, "provider": "secret"}),
        created_at="2026-09-24T00:00:00+00:00",
        parent_config=None,
        tasks=(),
        interrupts=(),
    )


def test_snapshot_projects_only_public_status_and_display_messages() -> None:
    result = project_session_snapshot(
        _state(
            [
                SystemMessage(content="private system prompt", id="system"),
                HumanMessage(content="hello", id="user-1"),
                AIMessage(content="hi", id="assistant-1"),
                ToolMessage(content="read result", tool_call_id="call-1", id="tool-1"),
            ]
        ),
        session_id="public-session",
        server_epoch="epoch-1",
        revision=3,
    )

    assert isinstance(result, SessionSnapshot)
    assert [message.role for message in result.messages] == ["user", "assistant", "tool"]
    assert [message.text for message in result.messages] == ["hello", "hi", "read result"]
    assert result.messages[-1].tool_call_id == "call-1"
    assert result.session_id == "public-session"
    assert result.checkpoint_id == "checkpoint-private"
    assert result.graph_status == "idle"
    assert result.message_count == 4
    assert "must-not-leak" not in result.model_dump_json()
    assert "secret" not in result.model_dump_json()
    assert "private system prompt" not in result.model_dump_json()


def test_snapshot_handles_partial_checkpoint_as_idle_without_fake_completion() -> None:
    state = _state([], next_nodes=("model",), checkpoint_id=None, status="ready")

    result = project_session_snapshot(
        state,
        session_id="partial",
        server_epoch="epoch-1",
        revision=0,
    )

    assert result.checkpoint_id is None
    assert result.graph_status == "interrupted"
    assert result.message_count == 0
    assert result.run_outcome is None


def test_snapshot_keeps_newest_messages_with_per_message_and_total_budgets() -> None:
    messages = [
        HumanMessage(content=f"{index}:" + "x" * 9000, id=f"m-{index}") for index in range(20)
    ]
    result = project_session_snapshot(
        _state(messages), session_id="s1", server_epoch="e1", revision=1
    )

    assert result.truncated
    assert len(result.messages) <= 20
    assert all(
        len(message.text.encode("utf-8")) <= MAX_DISPLAY_TEXT_BYTES for message in result.messages
    )
    assert (
        sum(len(message.text.encode("utf-8")) for message in result.messages)
        <= MAX_SNAPSHOT_TEXT_BYTES
    )
    assert result.messages[-1].message_id == "m-19"
