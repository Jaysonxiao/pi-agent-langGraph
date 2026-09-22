"""M6 vertical-slice tests for durable multi-turn session resume."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.domain.state import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.sessions import (
    SessionNotReadyError,
    open_sqlite_checkpointer,
    run_session_turn,
    session_config,
)


def test_session_turn_resumes_after_sqlite_checkpointer_reopens(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    first_model = ScriptedChatModel([AIMessage(content="remembered", id="assistant-1")])

    with open_sqlite_checkpointer(database_path) as checkpointer:
        first_result = run_session_turn(
            build_minimal_graph(checkpointer),
            session_id="session-1",
            content="remember alpha",
            message_id="user-1",
            context=RunContext(model=first_model),
        )

    second_model = ScriptedChatModel([AIMessage(content="alpha", id="assistant-2")])
    with open_sqlite_checkpointer(database_path) as checkpointer:
        second_result = run_session_turn(
            build_minimal_graph(checkpointer),
            session_id="session-1",
            content="what should you remember?",
            message_id="user-2",
            context=RunContext(model=second_model),
        )

    expected_history = (
        HumanMessage(content="remember alpha", id="user-1"),
        AIMessage(content="remembered", id="assistant-1"),
        HumanMessage(content="what should you remember?", id="user-2"),
    )
    assert first_result["status"] == "completed"
    assert second_model.calls == [expected_history]
    assert second_result["messages"] == [
        *expected_history,
        AIMessage(content="alpha", id="assistant-2"),
    ]


def test_session_turn_keeps_threads_isolated(tmp_path: Path) -> None:
    model = ScriptedChatModel(
        [
            AIMessage(content="one reply", id="assistant-1"),
            AIMessage(content="two reply", id="assistant-2"),
        ]
    )

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        graph = build_minimal_graph(checkpointer)
        run_session_turn(
            graph,
            session_id="session-1",
            content="one",
            message_id="user-1",
            context=RunContext(model=model),
        )
        run_session_turn(
            graph,
            session_id="session-2",
            content="two",
            message_id="user-2",
            context=RunContext(model=model),
        )

    assert model.calls == [
        (HumanMessage(content="one", id="user-1"),),
        (HumanMessage(content="two", id="user-2"),),
    ]


def test_session_turn_validates_new_user_input(tmp_path: Path) -> None:
    model = ScriptedChatModel([AIMessage(content="unused", id="assistant-1")])

    with (
        open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer,
        pytest.raises(ValueError, match="must not be blank"),
    ):
        run_session_turn(
            build_minimal_graph(checkpointer),
            session_id="session-1",
            content="   ",
            message_id="user-1",
            context=RunContext(model=model),
        )

    assert model.calls == []


def test_session_turn_rejects_a_thread_paused_before_a_node(tmp_path: Path) -> None:
    model = ScriptedChatModel([AIMessage(content="unused", id="assistant-1")])

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        graph = build_minimal_graph(checkpointer)
        graph.invoke(
            create_initial_state("paused input", message_id="user-1"),
            session_config("session-1"),
            context=RunContext(model=model),
            interrupt_before=["model"],
            durability="sync",
        )

        with pytest.raises(SessionNotReadyError, match="session-1"):
            run_session_turn(
                graph,
                session_id="session-1",
                content="must not bypass the pause",
                message_id="user-2",
                context=RunContext(model=model),
            )

    assert model.calls == []
