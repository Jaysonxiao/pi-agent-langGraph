"""Integration evidence for LangGraph update chunks and stable events."""

from collections.abc import Mapping

import pytest
from langchain_core.messages import AIMessage

from pi_agent.domain import create_initial_state
from pi_agent.events import project_update_chunks
from pi_agent.graph import RunContext, build_tool_graph
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.tools import RecordingAddHandler, ToolRegistry, create_add_tool


def test_tool_graph_updates_project_in_execution_order() -> None:
    model = ScriptedChatModel(
        [
            AIMessage(
                content="",
                id="assistant-tool-call",
                tool_calls=[{"name": "add", "args": {"left": 2, "right": 3}, "id": "call-1"}],
            ),
            AIMessage(content="The result is 5.", id="assistant-final"),
        ]
    )
    chunks = build_tool_graph().stream(
        create_initial_state("calculate 2 + 3"),
        context=RunContext(
            model=model,
            tools=ToolRegistry([create_add_tool(RecordingAddHandler())]),
        ),
        stream_mode="updates",
    )

    events = list(project_update_chunks(chunks))

    assert [event.sequence for event in events] == [0, 1, 2]
    assert [event.node for event in events] == ["model", "tools", "model"]
    assert [event.kind for event in events] == ["state_update", "tool", "state_update"]
    assert [event.payload["status"] for event in events] == [
        "awaiting_tools",
        "ready",
        "completed",
    ]
    assert all("messages" not in event.payload for event in events)


def test_update_adapter_rejects_non_mapping_node_update() -> None:
    malformed: list[Mapping[str, object]] = [{"model": "not-an-update-mapping"}]

    with pytest.raises(ValueError, match="mapping"):
        list(project_update_chunks(malformed))
