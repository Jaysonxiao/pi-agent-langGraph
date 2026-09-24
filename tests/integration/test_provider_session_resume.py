"""M8.9-R2-E provider-backed SQLite resume contracts."""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import run_provider_session
from pi_agent.domain.state import AgentState
from pi_agent.models import CompatibleAsyncChatModel


class ScriptedProviderClient:
    def __init__(self, replies: Sequence[AIMessage]) -> None:
        self._replies = list(replies)
        self.calls: list[tuple[AnyMessage, ...]] = []
        self.closed = False

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        del config
        self.calls.append(tuple(messages))
        return self._replies.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def test_provider_session_reopens_sqlite_and_sends_continuous_history(
    tmp_path: Path,
) -> None:
    client = ScriptedProviderClient(
        (
            AIMessage(content="remembered", id="assistant-1"),
            AIMessage(content="alpha", id="assistant-2"),
        )
    )
    model = CompatibleAsyncChatModel(client)
    options = ProviderCliOptions(
        provider="compatible",
        prompt="remember alpha",
        events="jsonl",
        database=tmp_path / "provider-resume.sqlite",
        session_id="provider-session",
        workspace=tmp_path,
    )

    async def scenario() -> tuple[AgentState, AgentState]:
        first = await run_provider_session(options, model=model, message_id="user-1")
        second = await run_provider_session(
            replace(options, prompt="what should you remember?"),
            model=model,
            message_id="user-2",
        )
        await model.aclose()
        return first, second

    first, second = asyncio.run(scenario())

    assert first["status"] == "completed"
    assert client.calls == [
        (HumanMessage(content="remember alpha", id="user-1"),),
        (
            HumanMessage(content="remember alpha", id="user-1"),
            AIMessage(content="remembered", id="assistant-1"),
            HumanMessage(content="what should you remember?", id="user-2"),
        ),
    ]
    assert second["messages"] == [
        HumanMessage(content="remember alpha", id="user-1"),
        AIMessage(content="remembered", id="assistant-1"),
        HumanMessage(content="what should you remember?", id="user-2"),
        AIMessage(content="alpha", id="assistant-2"),
    ]
    assert client.closed is True
