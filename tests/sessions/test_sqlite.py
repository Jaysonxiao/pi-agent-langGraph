"""Focused tests for the development SQLite checkpoint boundary."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.domain.state import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import FakeChatModel
from pi_agent.sessions import open_sqlite_checkpointer, session_config


def test_sqlite_checkpointer_persists_a_graph_turn(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"

    with open_sqlite_checkpointer(database_path) as checkpointer:
        graph = build_minimal_graph(checkpointer)
        result = graph.invoke(
            create_initial_state("hello", message_id="user-1"),
            session_config("session-1"),
            context=RunContext(model=FakeChatModel("stored")),
            durability="sync",
        )

    assert database_path.is_file()
    assert result["messages"] == [
        HumanMessage(content="hello", id="user-1"),
        AIMessage(content="stored", id="fake-assistant-1"),
    ]


def test_sqlite_checkpointer_rejects_a_directory_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be a file"), open_sqlite_checkpointer(tmp_path):
        pass
