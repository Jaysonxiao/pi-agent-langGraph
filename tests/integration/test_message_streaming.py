"""Real fake-graph evidence for LangGraph message-stream projection."""

from collections.abc import Mapping
from typing import cast

from langchain_core.messages import AIMessage, BaseMessage

from pi_agent.domain import create_initial_state
from pi_agent.events import project_message_chunk
from pi_agent.graph import RunContext, build_tool_graph
from pi_agent.models.fake import ScriptedChatModel


def test_fake_graph_message_stream_projects_stable_event() -> None:
    chunks = build_tool_graph().stream(
        create_initial_state("hello"),
        context=RunContext(
            model=ScriptedChatModel([AIMessage(content="done", id="assistant-final")])
        ),
        stream_mode="messages",
    )
    message, metadata = cast(
        tuple[BaseMessage, Mapping[str, object]],
        next(iter(chunks)),
    )

    event = project_message_chunk(message, metadata, 0)

    assert event.kind == "message"
    assert event.node == "model"
    assert event.payload == {
        "role": "assistant",
        "content": "done",
        "message_id": "assistant-final",
        "is_chunk": False,
    }
