"""Unit tests for application-owned SQLite session metadata."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pi_agent.sessions import SqliteSessionCatalog
from pi_agent.sessions.metadata import METADATA_SCHEMA_VERSION


def test_list_sessions_creates_the_catalog_schema_without_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"

    assert SqliteSessionCatalog(database_path).list_sessions() == []

    with sqlite3.connect(database_path) as connection:
        applied_versions = connection.execute(
            "SELECT version FROM pi_agent_schema_migrations"
        ).fetchall()
    assert applied_versions == [(METADATA_SCHEMA_VERSION,)]


def test_record_session_preserves_creation_time_and_touches_updated_time(tmp_path: Path) -> None:
    timestamps = iter(
        [
            datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 21, 10, 1, tzinfo=UTC),
        ]
    )
    catalog = SqliteSessionCatalog(tmp_path / "checkpoints.sqlite", clock=lambda: next(timestamps))

    created = catalog.record_session("session-1")
    touched = catalog.record_session("session-1")

    assert created.session_id == "session-1"
    assert touched.created_at == created.created_at
    assert touched.updated_at > created.updated_at
    assert catalog.list_sessions() == [touched]


def test_record_session_persists_across_catalog_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    created = SqliteSessionCatalog(database_path).record_session("session-1")

    assert SqliteSessionCatalog(database_path).list_sessions() == [created]


def test_record_session_normalizes_an_aware_clock_to_utc(tmp_path: Path) -> None:
    catalog = SqliteSessionCatalog(
        tmp_path / "checkpoints.sqlite",
        clock=lambda: datetime(2026, 9, 21, 18, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    record = catalog.record_session("session-1")

    assert record.created_at == "2026-09-21T10:00:00+00:00"
    assert record.updated_at == "2026-09-21T10:00:00+00:00"


def test_record_session_rejects_a_naive_clock(tmp_path: Path) -> None:
    catalog = SqliteSessionCatalog(
        tmp_path / "checkpoints.sqlite",
        clock=lambda: datetime(2026, 9, 21, 10, 0),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        catalog.record_session("session-1")
