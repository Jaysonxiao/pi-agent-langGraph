"""Red tests for the learner-owned M8.8-R2 async session runner."""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.domain import create_initial_state
from pi_agent.graph import AsyncRunContext, build_async_minimal_graph
from pi_agent.models import AsyncFakeChatModel
from pi_agent.sessions import (
    SessionNotReadyError,
    SessionRecord,
    open_async_sqlite_checkpointer,
    run_async_session_turn,
    session_config,
)


class RecordingCatalog:
    """Test double proving metadata is recorded only after a completed turn."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []

    def record_session(self, session_id: str) -> SessionRecord:
        self.session_ids.append(session_id)
        return SessionRecord(
            session_id=session_id,
            created_at="2026-09-23T10:00:00+00:00",
            updated_at="2026-09-23T10:00:00+00:00",
        )


def test_async_session_turn_resumes_after_sqlite_reopens(tmp_path: Path) -> None:
    database_path = tmp_path / "async-session.sqlite"

    async def scenario() -> None:
        first_model = AsyncFakeChatModel(AIMessage(content="remembered", id="assistant-1"))
        async with open_async_sqlite_checkpointer(database_path) as saver:
            first_result = await run_async_session_turn(
                build_async_minimal_graph(saver),
                session_id="session-1",
                content="remember alpha",
                message_id="user-1",
                context=AsyncRunContext(model=first_model),
            )

        second_model = AsyncFakeChatModel(AIMessage(content="alpha", id="assistant-2"))
        async with open_async_sqlite_checkpointer(database_path) as saver:
            second_result = await run_async_session_turn(
                build_async_minimal_graph(saver),
                session_id="session-1",
                content="what should you remember?",
                message_id="user-2",
                context=AsyncRunContext(model=second_model),
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

    asyncio.run(scenario())


def test_async_session_turn_rejects_a_paused_thread_without_model_call(tmp_path: Path) -> None:
    database_path = tmp_path / "async-paused.sqlite"

    async def scenario() -> None:
        model = AsyncFakeChatModel(AIMessage(content="unused", id="assistant-1"))
        async with open_async_sqlite_checkpointer(database_path) as saver:
            graph = build_async_minimal_graph(saver)
            await graph.ainvoke(
                create_initial_state("paused", message_id="user-1"),
                session_config("session-1"),
                context=AsyncRunContext(model=model),
                interrupt_before=["model"],
                durability="sync",
            )

            with pytest.raises(SessionNotReadyError, match="session-1"):
                await run_async_session_turn(
                    graph,
                    session_id="session-1",
                    content="must not bypass the pause",
                    message_id="user-2",
                    context=AsyncRunContext(model=model),
                )

        assert model.calls == []

    asyncio.run(scenario())


def test_async_session_turn_rejects_blank_content_before_model_call(tmp_path: Path) -> None:
    database_path = tmp_path / "async-input.sqlite"

    async def scenario() -> None:
        model = AsyncFakeChatModel(AIMessage(content="unused", id="assistant-1"))
        async with open_async_sqlite_checkpointer(database_path) as saver:
            with pytest.raises(ValueError, match="must not be blank"):
                await run_async_session_turn(
                    build_async_minimal_graph(saver),
                    session_id="session-1",
                    content="   ",
                    message_id="user-1",
                    context=AsyncRunContext(model=model),
                )

        assert model.calls == []

    asyncio.run(scenario())


def test_async_session_turn_records_catalog_after_success(tmp_path: Path) -> None:
    database_path = tmp_path / "async-metadata.sqlite"

    async def scenario() -> None:
        catalog = RecordingCatalog()
        async with open_async_sqlite_checkpointer(database_path) as saver:
            result = await run_async_session_turn(
                build_async_minimal_graph(saver),
                session_id="session-1",
                content="hello",
                message_id="user-1",
                context=AsyncRunContext(
                    model=AsyncFakeChatModel(AIMessage(content="done", id="assistant-1"))
                ),
                catalog=catalog,
            )

        assert result["status"] == "completed"
        assert catalog.session_ids == ["session-1"]

    asyncio.run(scenario())
