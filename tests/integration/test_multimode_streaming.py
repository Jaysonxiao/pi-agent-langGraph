"""Real LangGraph evidence for unified multi-mode event sequencing."""

from collections.abc import Iterable
from typing import cast

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from pi_agent.domain import AgentState, AgentStateUpdate, create_initial_state
from pi_agent.events import project_stream_chunks
from pi_agent.graph import RunContext
from pi_agent.graph.nodes import model_node
from pi_agent.models.fake import ScriptedChatModel


def _progress_model_node(state: AgentState, runtime: Runtime[RunContext]) -> AgentStateUpdate:
    get_stream_writer()(
        {
            "type": "progress",
            "node": "model",
            "message": "calling model",
            "completed": 0,
            "total": 1,
        }
    )
    return model_node(state, runtime)


def test_real_multimode_stream_has_one_global_event_sequence() -> None:
    builder = StateGraph(AgentState, context_schema=RunContext)
    builder.add_node("model", _progress_model_node)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    graph = builder.compile()

    raw_chunks = cast(
        Iterable[tuple[str, object]],
        graph.stream(
            create_initial_state("hello"),
            context=RunContext(
                model=ScriptedChatModel([AIMessage(content="done", id="assistant-final")])
            ),
            stream_mode=["updates", "messages", "custom"],
        ),
    )
    events = list(project_stream_chunks(raw_chunks))

    assert [event.sequence for event in events] == [0, 1, 2]
    assert [event.kind for event in events] == [
        "progress",
        "message",
        "state_update",
    ]
    assert [event.node for event in events] == ["model", "model", "model"]
