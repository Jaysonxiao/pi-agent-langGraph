"""Offline acceptance regression for the completed M8.8 provider path."""

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.read_only import create_cli_read_only_registry
from pi_agent.cli.runtime import run_provider_session
from pi_agent.models import AsyncFakeChatModel


def test_offline_provider_path_keeps_session_and_read_only_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("offline acceptance", encoding="utf-8")
    options = ProviderCliOptions(
        provider="fake",
        prompt="hello",
        events="jsonl",
        database=tmp_path / "acceptance.sqlite",
        session_id="acceptance-1",
        workspace=workspace,
    )

    async def scenario() -> None:
        result = await run_provider_session(
            options,
            model=AsyncFakeChatModel(AIMessage(content="offline", id="assistant-1")),
            message_id="user-1",
        )
        assert result["status"] == "completed"

    asyncio.run(scenario())

    registry = create_cli_read_only_registry(workspace)
    assert [tool.name for tool in registry.tools] == ["read", "list", "search"]
