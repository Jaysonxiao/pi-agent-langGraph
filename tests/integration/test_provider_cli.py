"""Red integration tests for the learner-owned M8.8-R4 runtime assembly."""

import asyncio
from dataclasses import replace
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import run_provider_session
from pi_agent.models import AsyncFakeChatModel


def test_provider_session_assembles_fake_model_and_persists_history(tmp_path: Path) -> None:
    options = ProviderCliOptions(
        provider="fake",
        prompt="remember alpha",
        events="jsonl",
        database=tmp_path / "provider.sqlite",
        session_id="session-1",
        workspace=tmp_path,
    )

    async def scenario() -> None:
        first = await run_provider_session(
            options,
            model=AsyncFakeChatModel(AIMessage(content="remembered", id="assistant-1")),
            message_id="user-1",
        )
        second_options = replace(options, prompt="what should you remember?")
        second = await run_provider_session(
            second_options,
            model=AsyncFakeChatModel(AIMessage(content="alpha", id="assistant-2")),
            message_id="user-2",
        )

        assert first["status"] == "completed"
        assert second["messages"] == [
            HumanMessage(content="remember alpha", id="user-1"),
            AIMessage(content="remembered", id="assistant-1"),
            HumanMessage(content="what should you remember?", id="user-2"),
            AIMessage(content="alpha", id="assistant-2"),
        ]

    asyncio.run(scenario())


def test_provider_session_uses_explicit_workspace_for_context(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use the workspace rules.", encoding="utf-8")
    options = ProviderCliOptions(
        provider="fake",
        prompt="hello",
        events="text",
        database=tmp_path / "provider-context.sqlite",
        session_id="session-1",
        workspace=tmp_path,
    )
    model = AsyncFakeChatModel(AIMessage(content="done", id="assistant-1"))

    async def scenario() -> None:
        await run_provider_session(options, model=model, message_id="user-1")

    asyncio.run(scenario())
    assert "Use the workspace rules." in str(model.calls[0])
