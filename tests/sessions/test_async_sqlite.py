"""Red tests for the learner-owned M8.8-R1 async SQLite boundary."""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.domain import create_initial_state
from pi_agent.graph import AsyncRunContext, build_async_minimal_graph
from pi_agent.models import AsyncFakeChatModel
from pi_agent.sessions import open_async_sqlite_checkpointer, session_config


def test_async_sqlite_checkpointer_persists_across_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "async-checkpoints.sqlite"

    async def scenario() -> None:
        first_model = AsyncFakeChatModel(AIMessage(content="stored", id="async-stored"))
        async with open_async_sqlite_checkpointer(database_path) as saver:
            graph = build_async_minimal_graph(saver)
            result = await graph.ainvoke(
                create_initial_state("hello", message_id="user-1"),
                session_config("session-1"),
                context=AsyncRunContext(model=first_model),
                durability="sync",
            )

        assert result["messages"] == [
            HumanMessage(content="hello", id="user-1"),
            AIMessage(content="stored", id="async-stored"),
        ]

        async with open_async_sqlite_checkpointer(database_path) as saver:
            reopened_graph = build_async_minimal_graph(saver)
            snapshot = await reopened_graph.aget_state(session_config("session-1"))

        assert snapshot.values["messages"] == result["messages"]

    asyncio.run(scenario())


def test_async_sqlite_checkpointer_rejects_a_directory_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="must be a file"):
            async with open_async_sqlite_checkpointer(tmp_path):
                pass

    asyncio.run(scenario())


def test_async_sqlite_checkpointer_keeps_database_owned_by_context(tmp_path: Path) -> None:
    database_path = tmp_path / "owned.sqlite"

    async def scenario() -> None:
        async with open_async_sqlite_checkpointer(database_path) as saver:
            await saver.conn.execute("SELECT 1")

        with pytest.raises(ValueError, match=r"(?i)(connection closed|no active connection)"):
            await saver.conn.execute("SELECT 1")

    asyncio.run(scenario())
