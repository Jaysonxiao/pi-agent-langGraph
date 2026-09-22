"""M6 integration coverage for checkpoint history after process reconstruction."""

from pathlib import Path

from langchain_core.messages import AIMessage

from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.sessions import (
    list_session_checkpoints,
    open_sqlite_checkpointer,
    run_session_turn,
)


def test_session_history_survives_reopening_and_is_newest_first(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    model = ScriptedChatModel(
        [
            AIMessage(content="first reply", id="assistant-1"),
            AIMessage(content="second reply", id="assistant-2"),
        ]
    )

    with open_sqlite_checkpointer(database_path) as checkpointer:
        graph = build_minimal_graph(checkpointer)
        run_session_turn(
            graph,
            session_id="session-1",
            content="first",
            message_id="user-1",
            context=RunContext(model=model),
        )
        run_session_turn(
            graph,
            session_id="session-1",
            content="second",
            message_id="user-2",
            context=RunContext(model=model),
        )

    with open_sqlite_checkpointer(database_path) as checkpointer:
        history = list_session_checkpoints(build_minimal_graph(checkpointer), "session-1")
        missing_history = list_session_checkpoints(
            build_minimal_graph(checkpointer), "missing-session"
        )

    assert history
    assert history[0].status == "completed"
    assert history[0].message_count == 4
    assert history[0].next_nodes == ()
    assert [item.created_at for item in history] == sorted(
        (item.created_at for item in history), reverse=True
    )
    assert len({item.checkpoint_id for item in history}) == len(history)
    assert missing_history == []
