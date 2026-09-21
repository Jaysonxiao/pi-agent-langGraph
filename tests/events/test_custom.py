"""Acceptance tests for stable custom progress events."""

import pytest

from pi_agent.events import StreamEvent, project_custom_chunk


def test_progress_kind_is_supported_by_strict_event_envelope() -> None:
    event = StreamEvent(
        sequence=0,
        kind="progress",
        node="worker",
        payload={"message": "working", "completed": 1, "total": 2},
    )

    assert event.model_dump_json()


def test_project_progress_chunk() -> None:
    event = project_custom_chunk(
        {
            "type": "progress",
            "node": "worker",
            "message": "working",
            "completed": 1,
            "total": 2,
        },
        sequence=3,
    )

    assert event == StreamEvent(
        sequence=3,
        kind="progress",
        node="worker",
        payload={"message": "working", "completed": 1, "total": 2},
    )


def test_custom_projection_rejects_unknown_event_type() -> None:
    with pytest.raises(ValueError, match="progress"):
        project_custom_chunk(
            {
                "type": "notice",
                "node": "worker",
                "message": "working",
                "completed": 1,
                "total": 2,
            },
            sequence=0,
        )


def test_custom_projection_validates_progress_fields() -> None:
    valid_chunk: dict[str, object] = {
        "type": "progress",
        "node": "worker",
        "message": "working",
        "completed": 1,
        "total": 2,
    }
    invalid_cases = (
        ({**valid_chunk, "node": ""}, "node"),
        ({**valid_chunk, "message": ""}, "message"),
        ({**valid_chunk, "completed": True}, "completed"),
        ({**valid_chunk, "total": 0}, "total"),
        ({**valid_chunk, "completed": 3}, "completed"),
    )

    for chunk, field_name in invalid_cases:
        with pytest.raises(ValueError, match=field_name):
            project_custom_chunk(chunk, sequence=0)
