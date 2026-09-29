"""Small additive UI tables; LangGraph checkpoint tables remain untouched."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pi_agent.sessions.metadata import SqliteSessionCatalog
from pi_agent.web.schemas import (
    DEFAULT_TOOL_CALL_LIMITS,
    Activity,
    RunItem,
    RunStatus,
    SessionEdit,
    SessionItem,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class WebStore:
    def __init__(self, database: Path, default_workspace: Path | None = None) -> None:
        self.database = database
        self.default_workspace = default_workspace.resolve() if default_workspace else Path.cwd()
        self.catalog = SqliteSessionCatalog(database)
        self.catalog.list_sessions()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_sessions (
                    session_id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0, workspace TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS web_runs (
                    run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, content_hash TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL,
                    finished_at TEXT, error TEXT,
                    UNIQUE(session_id, request_id));
                CREATE TABLE IF NOT EXISTS web_activity (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, run_id TEXT NOT NULL,
                    phase TEXT NOT NULL, tool_name TEXT, outcome TEXT,
                    created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS web_activity_session
                    ON web_activity(session_id, event_id);
                CREATE TABLE IF NOT EXISTS web_settings (
                    settings_id INTEGER PRIMARY KEY CHECK(settings_id=1),
                    workspace TEXT NOT NULL, tools_json TEXT NOT NULL,
                    tool_limits_json TEXT NOT NULL DEFAULT '{}');
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(web_sessions)")}
            if "workspace" not in columns:
                db.execute("ALTER TABLE web_sessions ADD COLUMN workspace TEXT NOT NULL DEFAULT ''")
            settings_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(web_settings)")
            }
            if "tool_limits_json" not in settings_columns:
                db.execute(
                    "ALTER TABLE web_settings ADD COLUMN tool_limits_json "
                    "TEXT NOT NULL DEFAULT '{}'"
                )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE web_runs SET status='needs_recovery', finished_at=?, error=? "
                "WHERE status='running'",
                (now(), "服务已重启, 上一轮结果需要核对。不会自动重新执行。"),
            )

    def settings(self) -> tuple[str, tuple[str, ...], dict[str, int]] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT workspace, tools_json, tool_limits_json "
                "FROM web_settings WHERE settings_id=1"
            ).fetchone()
        if row is None:
            return None
        tools = json.loads(row["tools_json"])
        tool_limits = json.loads(row["tool_limits_json"])
        if not tool_limits:
            tool_limits = DEFAULT_TOOL_CALL_LIMITS.copy()
        return row["workspace"], tuple(tools), tool_limits

    def save_settings(
        self, workspace: str, tools: tuple[str, ...], tool_limits: dict[str, int]
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO web_settings(settings_id,workspace,tools_json,tool_limits_json) "
                "VALUES (1,?,?,?) "
                "ON CONFLICT(settings_id) DO UPDATE SET workspace=excluded.workspace, "
                "tools_json=excluded.tools_json, tool_limits_json=excluded.tool_limits_json",
                (workspace, json.dumps(tools), json.dumps(tool_limits)),
            )

    def sessions(self, archived: bool = False) -> list[SessionItem]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT s.session_id, COALESCE(w.title, '历史会话') AS title, "
                "COALESCE(w.archived, 0) AS archived, "
                "COALESCE(NULLIF(w.workspace, ''), ?) AS workspace, s.created_at, s.updated_at "
                "FROM pi_agent_sessions s LEFT JOIN web_sessions w "
                "ON s.session_id=w.session_id WHERE COALESCE(w.archived, 0)=? "
                "ORDER BY s.updated_at DESC, s.session_id DESC LIMIT 500",
                (str(self.default_workspace), int(archived)),
            ).fetchall()
        return [SessionItem.model_validate(dict(row)) for row in rows]

    def session(self, session_id: str) -> SessionItem | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT s.session_id, COALESCE(w.title, '历史会话') AS title, "
                "COALESCE(w.archived, 0) AS archived, "
                "COALESCE(NULLIF(w.workspace, ''), ?) AS workspace, s.created_at, s.updated_at "
                "FROM pi_agent_sessions s LEFT JOIN web_sessions w "
                "ON s.session_id=w.session_id WHERE s.session_id=?",
                (str(self.default_workspace), session_id),
            ).fetchone()
        return SessionItem.model_validate(dict(row)) if row else None

    def create(self, session_id: str, workspace: Path | None = None) -> SessionItem:
        self.catalog.record_session(session_id)
        with self.connect() as db:
            db.execute(
                "INSERT INTO web_sessions(session_id,title,archived,workspace) "
                "VALUES (?, '新会话', 0, ?)",
                (session_id, str((workspace or self.default_workspace).resolve())),
            )
        result = self.session(session_id)
        assert result is not None
        return result

    def edit(self, session_id: str, edit: SessionEdit) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO web_sessions(session_id,title,archived,workspace) "
                "VALUES (?, '历史会话', 0, ?)",
                (session_id, str(self.default_workspace)),
            )
            if edit.title is not None:
                db.execute(
                    "UPDATE web_sessions SET title=? WHERE session_id=?", (edit.title, session_id)
                )
            if edit.archived is not None:
                db.execute(
                    "UPDATE web_sessions SET archived=? WHERE session_id=?",
                    (int(edit.archived), session_id),
                )

    def prior_run(self, session_id: str, request_id: str, text: str) -> RunItem | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM web_runs WHERE session_id=? AND request_id=?",
                (session_id, request_id),
            ).fetchone()
        if row is None:
            return None
        if row["content_hash"] != self._hash(text):
            raise ValueError("同一请求标识不能用于不同内容。")
        return RunItem.model_validate(dict(row))

    def add_run(self, session_id: str, run_id: str, request_id: str, text: str) -> RunItem:
        with self.connect() as db:
            db.execute(
                "INSERT INTO web_runs VALUES (?, ?, ?, ?, 'running', ?, NULL, NULL)",
                (run_id, session_id, request_id, self._hash(text), now()),
            )
            db.execute(
                "UPDATE web_sessions SET title=? WHERE session_id=? AND title='新会话'",
                (text[:40], session_id),
            )
        self.catalog.record_session(session_id)
        result = self.run(run_id)
        assert result is not None
        return result

    def run(self, run_id: str) -> RunItem | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM web_runs WHERE run_id=?", (run_id,)).fetchone()
        return RunItem.model_validate(dict(row)) if row else None

    def session_workspace(self, session_id: str) -> Path:
        item = self.session(session_id)
        if item is None:
            raise KeyError("Unknown session.")
        return Path(item.workspace)

    def latest_run(self, session_id: str) -> RunItem | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM web_runs WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return RunItem.model_validate(dict(row)) if row else None

    def finish(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE web_runs SET status=?, finished_at=?, error=? WHERE run_id=?",
                (status, now(), error, run_id),
            )

    def event(
        self,
        session_id: str,
        run_id: str,
        phase: str,
        tool_name: str | None = None,
        outcome: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO web_activity(session_id,run_id,phase,tool_name,outcome,created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, run_id, phase, tool_name, outcome, now()),
            )
            db.execute(
                "DELETE FROM web_activity WHERE session_id=? AND event_id NOT IN "
                "(SELECT event_id FROM web_activity WHERE session_id=? "
                "ORDER BY event_id DESC LIMIT 256)",
                (session_id, session_id),
            )

    def events(self, session_id: str, after: int = 0) -> list[Activity]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM web_activity WHERE session_id=? AND event_id>? ORDER BY event_id",
                (session_id, after),
            ).fetchall()
        return [Activity.model_validate(dict(row)) for row in rows]

    def event_detail(self, session_id: str, event_id: int) -> Activity | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM web_activity WHERE session_id=? AND event_id=?",
                (session_id, event_id),
            ).fetchone()
        return Activity.model_validate(dict(row)) if row else None

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
