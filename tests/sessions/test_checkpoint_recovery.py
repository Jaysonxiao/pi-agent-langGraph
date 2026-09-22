"""Failure contracts for unreadable durable checkpoint storage."""

import sqlite3
from pathlib import Path
from re import escape

import pytest

from pi_agent.graph import build_minimal_graph
from pi_agent.sessions import (
    SessionCheckpointError,
    open_sqlite_checkpointer,
    session_config,
)


def test_checkpointer_translates_an_unreadable_database_to_a_session_error(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    database_path.write_bytes(b"this is not a sqlite database")

    with (
        pytest.raises(SessionCheckpointError, match=escape(str(database_path.resolve()))) as error,
        open_sqlite_checkpointer(database_path) as checkpointer,
    ):
        build_minimal_graph(checkpointer).get_state(session_config("session-1"))

    assert isinstance(error.value.__cause__, sqlite3.DatabaseError)
