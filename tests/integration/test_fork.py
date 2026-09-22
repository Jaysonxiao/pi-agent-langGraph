"""M6 integration coverage for isolated checkpoint branches."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from pi_agent.domain.state import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.sessions import (
    SessionForkError,
    fork_session,
    list_session_checkpoints,
    open_sqlite_checkpointer,
    run_session_turn,
    session_config,
)


def test_fork_session_branches_from_selected_checkpoint_without_mutating_source(
    tmp_path: Path,
) -> None:
    model = ScriptedChatModel(
        [
            AIMessage(content="first reply", id="assistant-1"),
            AIMessage(content="second reply", id="assistant-2"),
            AIMessage(content="branch reply", id="assistant-3"),
        ]
    )

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        graph = build_minimal_graph(checkpointer)
        run_session_turn(
            graph,
            session_id="source",
            content="first",
            message_id="user-1",
            context=RunContext(model=model),
        )
        run_session_turn(
            graph,
            session_id="source",
            content="second",
            message_id="user-2",
            context=RunContext(model=model),
        )
        selected = next(
            item
            for item in list_session_checkpoints(graph, "source")
            if item.status == "completed" and item.message_count == 2
        )
        calls_before_fork = list(model.calls)

        forked = fork_session(
            graph,
            source_session_id="source",
            checkpoint_id=selected.checkpoint_id,
            target_session_id="branch",
        )
        assert model.calls == calls_before_fork
        branch_result = run_session_turn(
            graph,
            session_id="branch",
            content="branch",
            message_id="user-3",
            context=RunContext(model=model),
        )
        source_state = graph.get_state(session_config("source"))

    assert forked.status == "completed"
    assert forked.message_count == 2
    assert forked.next_nodes == ()
    assert [message.content for message in branch_result["messages"]] == [
        "first",
        "first reply",
        "branch",
        "branch reply",
    ]
    assert [message.content for message in source_state.values["messages"]] == [
        "first",
        "first reply",
        "second",
        "second reply",
    ]


def test_fork_session_rejects_an_existing_target(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        [
            AIMessage(content="source reply", id="assistant-1"),
            AIMessage(content="target reply", id="assistant-2"),
        ]
    )

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        graph = build_minimal_graph(checkpointer)
        run_session_turn(
            graph,
            session_id="source",
            content="source",
            message_id="user-1",
            context=RunContext(model=model),
        )
        run_session_turn(
            graph,
            session_id="target",
            content="target",
            message_id="user-2",
            context=RunContext(model=model),
        )
        selected = next(
            item for item in list_session_checkpoints(graph, "source") if item.status == "completed"
        )

        with pytest.raises(SessionForkError, match="target"):
            fork_session(
                graph,
                source_session_id="source",
                checkpoint_id=selected.checkpoint_id,
                target_session_id="target",
            )


def test_fork_session_rejects_a_missing_source_checkpoint(tmp_path: Path) -> None:
    with (
        open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer,
        pytest.raises(SessionForkError, match="missing-checkpoint"),
    ):
        fork_session(
            build_minimal_graph(checkpointer),
            source_session_id="source",
            checkpoint_id="missing-checkpoint",
            target_session_id="branch",
        )


def test_fork_session_rejects_a_completed_status_with_pending_nodes(tmp_path: Path) -> None:
    model = ScriptedChatModel([AIMessage(content="unused", id="assistant-1")])

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        graph = build_minimal_graph(checkpointer)
        source_config = session_config("source")
        graph.invoke(
            create_initial_state("paused", message_id="user-1"),
            source_config,
            context=RunContext(model=model),
            interrupt_before=["model"],
            durability="sync",
        )
        graph.update_state(source_config, {"status": "completed"}, as_node="__start__")
        source_snapshot = graph.get_state(source_config)
        checkpoint_id = source_snapshot.config["configurable"]["checkpoint_id"]
        assert isinstance(checkpoint_id, str)
        assert source_snapshot.next == ("model",)

        with pytest.raises(SessionForkError, match=checkpoint_id):
            fork_session(
                graph,
                source_session_id="source",
                checkpoint_id=checkpoint_id,
                target_session_id="branch",
            )
        assert graph.get_state(session_config("branch")).created_at is None

    assert model.calls == []
