"""Metadata wiring tests for persistent session turns."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from pi_agent.domain.state import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import ScriptedChatModel
from pi_agent.sessions import (
    SessionNotReadyError,
    open_sqlite_checkpointer,
    run_session_turn,
    session_config,
)
from pi_agent.sessions.metadata import SessionRecord


class RecordingCatalog:
    """Test double proving runtime ordering without SQLite implementation details."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []

    def record_session(self, session_id: str) -> SessionRecord:
        self.session_ids.append(session_id)
        return SessionRecord(
            session_id=session_id,
            created_at="2026-09-21T10:00:00+00:00",
            updated_at="2026-09-21T10:00:00+00:00",
        )


def test_run_session_turn_records_metadata_after_graph_reaches_terminal_state(
    tmp_path: Path,
) -> None:
    catalog = RecordingCatalog()

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        result = run_session_turn(
            build_minimal_graph(checkpointer),
            session_id="session-1",
            content="hello",
            message_id="user-1",
            context=RunContext(
                model=ScriptedChatModel([AIMessage(content="done", id="assistant-1")])
            ),
            catalog=catalog,
        )

    assert result["status"] == "completed"
    assert catalog.session_ids == ["session-1"]


def test_run_session_turn_does_not_record_metadata_for_a_paused_thread(tmp_path: Path) -> None:
    catalog = RecordingCatalog()
    model = ScriptedChatModel([AIMessage(content="unused", id="assistant-1")])

    with open_sqlite_checkpointer(tmp_path / "checkpoints.sqlite") as checkpointer:
        graph = build_minimal_graph(checkpointer)
        graph.invoke(
            create_initial_state("paused", message_id="user-1"),
            session_config("session-1"),
            context=RunContext(model=model),
            interrupt_before=["model"],
            durability="sync",
        )

        with pytest.raises(SessionNotReadyError):
            run_session_turn(
                graph,
                session_id="session-1",
                content="must not record",
                message_id="user-2",
                context=RunContext(model=model),
                catalog=catalog,
            )

    assert catalog.session_ids == []
