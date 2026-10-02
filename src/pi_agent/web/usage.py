"""Durable Web-only accounting of physical model attempts, with explicit unknowns."""

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Literal, cast
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models.async_adapter import AsyncStreamingProviderClient
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.usage import TokenUsage, normalize_usage
from pi_agent.web.schemas import TokenTotals, UsageView
from pi_agent.web.store import WebStore, now

AttemptStatus = Literal["pending", "completed", "failed", "cancelled", "interrupted"]


class WebUsageStore:
    def __init__(self, store: WebStore) -> None:
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS web_model_usage (
                    attempt_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT,
                    status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
                    total_tokens INTEGER);
                CREATE INDEX IF NOT EXISTS web_model_usage_session
                    ON web_model_usage(session_id);
                CREATE TABLE IF NOT EXISTS web_usage_state (
                    state_id INTEGER PRIMARY KEY CHECK(state_id=1), revision INTEGER NOT NULL,
                    legacy_before TEXT NOT NULL, imported INTEGER NOT NULL DEFAULT 0);
            """)
            db.execute("INSERT OR IGNORE INTO web_usage_state VALUES (1,0,?,0)", (now(),))
            changed = db.execute(
                "UPDATE web_model_usage SET status='interrupted' WHERE status='pending'"
            ).rowcount
            if changed:
                db.execute("UPDATE web_usage_state SET revision=revision+1 WHERE state_id=1")

    def migration_state(self) -> tuple[str, bool]:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT legacy_before,imported FROM web_usage_state WHERE state_id=1"
            ).fetchone()
        return str(row[0]), bool(row[1])

    def import_history(
        self, records: Sequence[tuple[str, str, Mapping[str, object] | None]]
    ) -> None:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for identity, session, metadata in records:
                usage = safe_usage(metadata)
                db.execute(
                    "INSERT OR IGNORE INTO web_model_usage VALUES (?,?,NULL,'completed',?,?,?)",
                    (
                        identity,
                        session,
                        usage.input_tokens,
                        usage.output_tokens,
                        usage.total_tokens,
                    ),
                )
            db.execute("UPDATE web_usage_state SET imported=1,revision=revision+1 WHERE state_id=1")

    def begin(self, session: str, run: str) -> str:
        identity = uuid4().hex
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO web_model_usage VALUES (?,?,?,'pending',NULL,NULL,NULL)",
                (identity, session, run),
            )
            db.execute("UPDATE web_usage_state SET revision=revision+1 WHERE state_id=1")
        return identity

    def record(
        self, identity: str, metadata: Mapping[str, object] | None, status: AttemptStatus
    ) -> None:
        usage = safe_usage(metadata)
        with self.store.connect() as db:
            db.execute(
                "UPDATE web_model_usage SET status=?,input_tokens=?,output_tokens=?,total_tokens=? "
                "WHERE attempt_id=?",
                (status, usage.input_tokens, usage.output_tokens, usage.total_tokens, identity),
            )
            db.execute("UPDATE web_usage_state SET revision=revision+1 WHERE state_id=1")

    def revision(self) -> int:
        with self.store.connect() as db:
            return int(
                db.execute("SELECT revision FROM web_usage_state WHERE state_id=1").fetchone()[0]
            )

    def snapshot(self, session: str | None, epoch: str) -> UsageView:
        query = """SELECT COUNT(*) AS recorded_calls,
            SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
            SUM(total_tokens) AS total_tokens,
            COALESCE(SUM(status='pending'),0) AS pending_calls,
            COALESCE(SUM(status!='pending' AND (status!='completed' OR input_tokens IS NULL
                OR output_tokens IS NULL OR total_tokens IS NULL)),0) AS unknown_calls
            FROM web_model_usage"""
        with self.store.connect() as db:
            db.execute("BEGIN")
            revision = int(
                db.execute("SELECT revision FROM web_usage_state WHERE state_id=1").fetchone()[0]
            )
            overall = dict(db.execute(query).fetchone())
            current = dict(db.execute(query + " WHERE session_id=?", (session,)).fetchone())
        for item in (overall, current):
            if not item["recorded_calls"]:
                item.update(input_tokens=0, output_tokens=0, total_tokens=0)
        return UsageView(
            server_epoch=epoch,
            revision=revision,
            session_id=session,
            overall=TokenTotals.model_validate(overall),
            session=TokenTotals.model_validate(current),
        )


def safe_usage(metadata: Mapping[str, object] | None) -> TokenUsage:
    try:
        usage = normalize_usage(metadata)
    except ValueError:
        return normalize_usage(None)
    if (
        usage.total_tokens is None
        and usage.input_tokens is not None
        and usage.output_tokens is not None
    ):
        return TokenUsage(
            usage.input_tokens,
            usage.output_tokens,
            usage.input_tokens + usage.output_tokens,
            usage.source,
        )
    return usage


class WebUsageModel:
    """Observe requests before retries/graph commits; never own or close the shared model."""

    def __init__(self, model: AsyncChatModel, store: WebUsageStore, session: str, run: str) -> None:
        self.model, self.store, self.session, self.run = model, store, session, run

    @property
    def supports_streaming(self) -> bool:
        return isinstance(self.model, AsyncStreamingProviderClient) and bool(
            getattr(self.model, "supports_streaming", True)
        )

    def bind_tools(self, tools: Sequence[Mapping[str, object]]) -> "WebUsageModel":
        binder = getattr(self.model, "bind_tools", None)
        if callable(binder) and getattr(self.model, "supports_tool_binding", True):
            bound = binder(tools)
            if bound is not None:
                return WebUsageModel(bound, self.store, self.session, self.run)
        return self

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        identity = self.store.begin(self.session, self.run)
        try:
            reply = await self.model.ainvoke(messages, config)
        except asyncio.CancelledError:
            self.store.record(identity, None, "cancelled")
            raise
        except Exception:
            self.store.record(identity, None, "failed")
            raise
        self.store.record(identity, reply.usage_metadata, "completed")
        return reply

    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        identity = self.store.begin(self.session, self.run)
        metadata: Mapping[str, object] | None = None
        status: AttemptStatus = "failed"
        raw = None
        try:
            raw = cast(AsyncStreamingProviderClient, self.model).astream(messages, config)
            async for chunk in raw:
                if chunk.usage_metadata is not None:
                    metadata = chunk.usage_metadata
                    self.store.record(identity, metadata, "pending")
                yield chunk
            status = "completed"
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            try:
                self.store.record(identity, metadata, status)
            finally:
                close = getattr(raw, "aclose", None)
                if callable(close):
                    await close()

    async def aclose(self) -> None:
        """The app owns the underlying provider lifecycle."""
