"""Real LangGraph evidence for custom progress-stream projection."""

from typing import TypedDict, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from pi_agent.events import project_custom_chunk


class _ProgressState(TypedDict):
    value: int


def _worker(state: _ProgressState) -> dict[str, int]:
    writer = get_stream_writer()
    writer(
        {
            "type": "progress",
            "node": "worker",
            "message": "working",
            "completed": 1,
            "total": 2,
        }
    )
    return {"value": state["value"] + 1}


def test_real_custom_stream_projects_progress_event() -> None:
    builder = StateGraph(_ProgressState)
    builder.add_node("worker", _worker)
    builder.add_edge(START, "worker")
    builder.add_edge("worker", END)
    graph = builder.compile()

    raw_chunk = cast(
        dict[str, object],
        next(iter(graph.stream({"value": 0}, stream_mode="custom"))),
    )
    event = project_custom_chunk(raw_chunk, sequence=0)

    assert event.kind == "progress"
    assert event.node == "worker"
    assert event.payload == {"message": "working", "completed": 1, "total": 2}
