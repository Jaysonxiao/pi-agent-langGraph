"""History is pinned to a checkpoint and exposes only bounded display content."""

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import StateSnapshot

from pi_agent.web.service import project_history


def test_history_pages_do_not_overlap_and_hide_internal_fields() -> None:
    state = StateSnapshot(
        values={
            "messages": [SystemMessage(content="private-system")]
            + [
                HumanMessage(content="中文" * 12000 if i == 75 else str(i), id=f"id-{i}")
                for i in range(90)
            ],
            "api_key": "secret-provider",
        },
        next=(),
        config={"configurable": {"checkpoint_id": "pinned"}},
        metadata=None,
        created_at="now",
        parent_config=None,
        tasks=(),
        interrupts=(),
    )
    latest = project_history(state)
    previous = project_history(state, latest.next_before)
    first = project_history(state, previous.next_before)
    messages = first.messages + previous.messages + latest.messages
    assert [m.message_id for m in messages] == [f"id-{i}" for i in range(90)]
    assert first.next_before is None
    assert all(len(m.text.encode("utf-8")) <= 16384 for m in messages)
    assert messages[75].truncated
    assert latest.checkpoint_id == "pinned"
    assert "private-system" not in first.model_dump_json()
    assert "secret-provider" not in latest.model_dump_json()
