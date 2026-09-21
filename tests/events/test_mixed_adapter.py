"""Acceptance tests for the unified multi-mode stream adapter."""

import pytest
from langchain_core.messages import AIMessage

from pi_agent.events import project_stream_chunks


def test_mixed_adapter_preserves_order_and_assigns_one_global_sequence() -> None:
    raw_chunks: list[tuple[str, object]] = [
        (
            "custom",
            {
                "type": "progress",
                "node": "model",
                "message": "calling model",
                "completed": 0,
                "total": 1,
            },
        ),
        (
            "messages",
            (
                AIMessage(content="done", id="assistant-final"),
                {"langgraph_node": "model", "internal": "do not copy"},
            ),
        ),
        (
            "updates",
            {
                "model": {"status": "completed", "error": None},
                "tools": {"status": "ready", "tool_rounds": 1},
            },
        ),
    ]

    events = list(project_stream_chunks(raw_chunks))

    assert [event.sequence for event in events] == [0, 1, 2, 3]
    assert [event.kind for event in events] == [
        "progress",
        "message",
        "state_update",
        "tool",
    ]
    assert [event.node for event in events] == ["model", "model", "model", "tools"]


def test_mixed_adapter_rejects_malformed_mode_payloads() -> None:
    invalid_cases: tuple[tuple[list[tuple[str, object]], str], ...] = (
        ([("unknown", {})], "mode"),
        ([("updates", {"model": "not-a-mapping"})], "mapping"),
        ([("updates", {"": {"status": "completed"}})], "node"),
        ([("messages", ("not-a-message", {}))], "messages"),
        ([("custom", "not-a-mapping")], "custom"),
    )

    for raw_chunks, error_pattern in invalid_cases:
        with pytest.raises(ValueError, match=error_pattern):
            list(project_stream_chunks(raw_chunks))
