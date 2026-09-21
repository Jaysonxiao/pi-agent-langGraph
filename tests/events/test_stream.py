"""Acceptance tests for the first M5 stable streaming-event slice."""

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from pi_agent.events.stream import StreamEvent, project_stream_update


def test_stream_event_is_strict_and_json_serializable() -> None:
    event = StreamEvent(
        sequence=0,
        kind="state_update",
        node="model",
        payload={"status": "completed"},
    )

    assert event.model_dump(mode="json") == {
        "sequence": 0,
        "kind": "state_update",
        "node": "model",
        "payload": {"status": "completed"},
    }
    with pytest.raises(ValidationError):
        StreamEvent(sequence=-1, kind="state_update", node="model", payload={})


def test_project_model_update() -> None:
    event = project_stream_update("model", {"status": "completed"}, 4)

    assert event == StreamEvent(
        sequence=4,
        kind="state_update",
        node="model",
        payload={"status": "completed"},
    )


def test_project_tool_update() -> None:
    event = project_stream_update("tools", {"tool_rounds": 1, "status": "ready"}, 5)

    assert event.kind == "tool"
    assert event.payload == {"tool_rounds": 1, "status": "ready"}


def test_project_error_update() -> None:
    event = project_stream_update(
        "model",
        {"error": {"code": "model_error", "message": "offline"}},
        6,
    )

    assert event.kind == "error"
    assert event.payload["error"] == {"code": "model_error", "message": "offline"}


def test_project_update_excludes_message_objects_from_json_payload() -> None:
    event = project_stream_update(
        "model",
        {
            "messages": [AIMessage(content="done", id="assistant-final")],
            "status": "completed",
            "error": None,
        },
        7,
    )

    assert event.payload == {"status": "completed", "error": None}
    assert event.model_dump_json()
