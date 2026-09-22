"""Application-owned session metadata, separate from LangGraph checkpoints."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pi_agent.sessions.config import session_config

METADATA_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Stable metadata for one application session."""

    session_id: str
    created_at: str
    updated_at: str


class SessionCatalog(Protocol):
    """Application metadata boundary used by the session runtime."""

    def record_session(self, session_id: str) -> SessionRecord:
        """Create or touch metadata for one completed graph invocation."""
        ...


class SqliteSessionCatalog:
    """Small metadata catalog sharing the development checkpoint database file."""

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._database_path = database_path.resolve(strict=False)
        self._clock = clock or _utc_now

    def list_sessions(self) -> list[SessionRecord]:
        """List metadata rows newest first without exposing checkpoint internals."""
        with self._connect() as connection:
            self._migrate(connection)
            rows = connection.execute(
                """
                SELECT session_id, created_at, updated_at
                FROM pi_agent_sessions
                ORDER BY updated_at DESC, session_id ASC
                """
            ).fetchall()

        return [SessionRecord(*row) for row in rows]

    def record_session(self, session_id: str) -> SessionRecord:
        """Insert or touch one session while preserving its original creation time."""
        # 与 checkpoint thread 共用同一套 session ID 规则, 但不读 LangGraph 表.
        session_config(session_id)
        timestamp = _utc_iso(self._clock())

        with self._connect() as connection:
            self._migrate(connection)
            # 冲突时只碰 updated_at, 首次 created_at 必须原样保留.
            row = connection.execute(
                """
                INSERT INTO pi_agent_sessions(session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                RETURNING session_id, created_at, updated_at
                """,
                (session_id, timestamp, timestamp),
            ).fetchone()

        return SessionRecord(*row)

    def _connect(self) -> sqlite3.Connection:
        if self._database_path.exists() and not self._database_path.is_file():
            raise ValueError(f"Metadata path must be a file: {self._database_path}")
        if not self._database_path.parent.is_dir():
            raise ValueError(
                f"Metadata parent directory does not exist: {self._database_path.parent}"
            )
        return sqlite3.connect(self._database_path)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pi_agent_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = connection.execute(
            "SELECT 1 FROM pi_agent_schema_migrations WHERE version = ?",
            (METADATA_SCHEMA_VERSION,),
        ).fetchone()
        if applied is not None:
            return

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pi_agent_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO pi_agent_schema_migrations(version, applied_at) VALUES (?, ?)",
            (METADATA_SCHEMA_VERSION, _utc_now().isoformat()),
        )


def _utc_iso(value: datetime) -> str:
    """Persist one clock reading as UTC ISO-8601; naive datetimes are rejected."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("Session metadata clock must be timezone-aware.")
    return value.astimezone(UTC).isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)
