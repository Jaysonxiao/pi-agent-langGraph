"""Real graph evidence for terminal-state event filtering."""

from collections.abc import Iterable
from typing import cast

from langchain_core.messages import AIMessage

from pi_agent.domain import create_initial_state
from pi_agent.events import iter_terminal_once, project_stream_chunks
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import ScriptedChatModel


def test_real_graph_terminal_state_is_emitted_once() -> None:
    raw_chunks = cast(
        Iterable[tuple[str, object]],
        build_minimal_graph().stream(
            create_initial_state("hello"),
            context=RunContext(
                model=ScriptedChatModel([AIMessage(content="done", id="assistant-final")])
            ),
            stream_mode=["updates", "messages"],
        ),
    )
    events = list(iter_terminal_once(project_stream_chunks(raw_chunks)))

    terminal_events = [
        event
        for event in events
        if event.kind == "state_update" and event.payload.get("status") == "completed"
    ]
    assert len(terminal_events) == 1
