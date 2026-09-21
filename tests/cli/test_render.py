"""Acceptance tests for the pure CLI text renderer."""

from pi_agent.cli import render_event
from pi_agent.events import StreamEvent


def test_render_progress_event() -> None:
    event = StreamEvent(
        sequence=0,
        kind="progress",
        node="model",
        payload={"message": "calling model", "completed": 0, "total": 1},
    )

    assert render_event(event) == "[progress] model: calling model (0/1)"


def test_render_message_event_with_role_and_content() -> None:
    event = StreamEvent(
        sequence=1,
        kind="message",
        node="model",
        payload={
            "role": "assistant",
            "content": "done",
            "message_id": "assistant-final",
            "is_chunk": False,
        },
    )

    assert render_event(event) == "[message] model/assistant: done"


def test_render_error_and_generic_state_events() -> None:
    error = StreamEvent(
        sequence=2,
        kind="error",
        node="model",
        payload={"code": "model_error", "message": "offline"},
    )
    state = StreamEvent(
        sequence=3,
        kind="state_update",
        node="model",
        payload={"status": "completed", "error": None},
    )

    assert render_event(error) == "[error] model: offline"
    assert render_event(state) == '[state_update] model: {"status":"completed","error":null}'
