"""Red tests for the learner-owned M8.6-R2 tool-call chunk completion."""

import pytest
from langchain_core.messages import AIMessageChunk

from pi_agent.events import assemble_tool_call_message


def test_assembler_merges_interleaved_fragments_by_index() -> None:
    first = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "read", "args": '{"path":"', "id": "call-read", "index": 0},
            {"name": "list", "args": '{"path":"', "id": "call-list", "index": 1},
        ],
    )
    second = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": None, "args": 'README.md"}', "id": None, "index": 0},
            {"name": None, "args": 'src"}', "id": None, "index": 1},
        ],
    )

    message = assemble_tool_call_message([first, second])

    assert message.content == ""
    assert message.tool_calls == [
        {
            "name": "read",
            "args": {"path": "README.md"},
            "id": "call-read",
            "type": "tool_call",
        },
        {
            "name": "list",
            "args": {"path": "src"},
            "id": "call-list",
            "type": "tool_call",
        },
    ]


def test_assembler_rejects_incomplete_arguments_without_content_leak() -> None:
    secret = "incomplete-arguments-secret"
    partial = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "read", "args": '{"path":"' + secret, "id": "call-read", "index": 0}
        ],
    )

    with pytest.raises(ValueError, match="arguments") as raised:
        assemble_tool_call_message([partial])

    assert secret not in str(raised.value)


def test_assembler_rejects_call_without_stable_id() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "read", "args": '{"path":"README.md"}', "id": None, "index": 0}],
    )

    with pytest.raises(ValueError, match="id"):
        assemble_tool_call_message([chunk])


def test_assembler_rejects_conflicting_name_or_id_for_one_index() -> None:
    first = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "read", "args": '{"path":"', "id": "call-read", "index": 0}],
    )
    conflicting = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "write", "args": 'README.md"}', "id": "call-write", "index": 0}],
    )

    with pytest.raises(ValueError, match="fragment"):
        assemble_tool_call_message([first, conflicting])
