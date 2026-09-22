"""Recovery and parallel-write contracts for the session metadata catalog."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pi_agent.sessions import SqliteSessionCatalog
from pi_agent.sessions.metadata import METADATA_SCHEMA_VERSION


def test_catalog_recovers_when_table_exists_before_migration_marker(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE pi_agent_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE pi_agent_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    assert SqliteSessionCatalog(database_path).list_sessions() == []

    with sqlite3.connect(database_path) as connection:
        applied_versions = connection.execute(
            "SELECT version FROM pi_agent_schema_migrations"
        ).fetchall()
    assert applied_versions == [(METADATA_SCHEMA_VERSION,)]


def test_catalog_allows_independent_catalogs_to_record_sessions_in_parallel(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda session_id: SqliteSessionCatalog(database_path).record_session(session_id),
                ("session-1", "session-2"),
            )
        )

    session_ids = {
        record.session_id for record in SqliteSessionCatalog(database_path).list_sessions()
    }
    assert session_ids == {"session-1", "session-2"}
