"""Acceptance tests for stable message and token events."""

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from pi_agent.events import StreamEvent, project_message_chunk


def test_message_kind_is_supported_by_strict_event_envelope() -> None:
    event = StreamEvent(
        sequence=0,
        kind="message",
        node="model",
        payload={
            "role": "assistant",
            "content": "done",
            "message_id": "assistant-final",
            "is_chunk": False,
        },
    )

    assert event.model_dump_json()


def test_project_complete_assistant_message() -> None:
    event = project_message_chunk(
        AIMessage(content="done", id="assistant-final"),
        {"langgraph_node": "model", "internal": object()},
        3,
    )

    assert event == StreamEvent(
        sequence=3,
        kind="message",
        node="model",
        payload={
            "role": "assistant",
            "content": "done",
            "message_id": "assistant-final",
            "is_chunk": False,
        },
    )


def test_project_assistant_token_chunk() -> None:
    event = project_message_chunk(
        AIMessageChunk(content="hel", id="assistant-chunk"),
        {"langgraph_node": "model"},
        4,
    )

    assert event.payload == {
        "role": "assistant",
        "content": "hel",
        "message_id": "assistant-chunk",
        "is_chunk": True,
    }


def test_message_projection_requires_node_metadata() -> None:
    with pytest.raises(ValueError, match="langgraph_node"):
        project_message_chunk(AIMessage(content="done"), {}, 0)
