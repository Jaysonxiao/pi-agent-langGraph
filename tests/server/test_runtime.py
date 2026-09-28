"""Server runtime reuses async graph tools and durable session checkpoints."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.extensions import HookEvent, HookRegistry
from pi_agent.models import AsyncFakeChatModel
from pi_agent.runtime.session import SessionRuntimeConfig
from pi_agent.server.runtime import ServerSessionRuntime


class _ReadThenReplyModel:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        del messages, config
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                id="assistant-read",
                tool_calls=[
                    {
                        "name": "read",
                        "args": {"path": "probe.txt"},
                        "id": "call-read",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="The probe says ready.", id="assistant-final")


def test_server_runtime_reads_workspace_file_and_reopens_same_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "probe.txt").write_text("probe is ready", encoding="utf-8")
    config = SessionRuntimeConfig(
        database=tmp_path / "sessions.sqlite",
        workspace=workspace,
        session_id="remote-session",
    )

    async def scenario() -> None:
        first = await ServerSessionRuntime(
            model=_ReadThenReplyModel(), server_epoch="epoch-1"
        ).prompt(config, content="Read probe.txt", message_id="user-1")
        assert any(
            isinstance(message, ToolMessage) and "probe is ready" in message.content
            for message in first["messages"]
        )
        assert first["messages"][-1].content == "The probe says ready."

        await ServerSessionRuntime(
            model=AsyncFakeChatModel(AIMessage(content="Second turn.")), server_epoch="epoch-2"
        ).prompt(config, content="Continue", message_id="user-2")
        reopened = await ServerSessionRuntime(
            model=AsyncFakeChatModel(AIMessage(content="unused")), server_epoch="epoch-3"
        ).snapshot(config, revision=2)
        assert [message.text for message in reopened.messages][-2:] == ["Continue", "Second turn."]

    asyncio.run(scenario())


def test_server_runtime_preserves_hook_thread_and_run_correlation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[HookEvent] = []
    hooks = HookRegistry()

    async def record(event: HookEvent) -> None:
        events.append(event)

    hooks.register("capture", record)
    config = SessionRuntimeConfig(
        database=tmp_path / "sessions.sqlite",
        workspace=workspace,
        session_id="hook-session",
        hooks=hooks,
        run_id="run-42",
    )

    async def scenario() -> None:
        await ServerSessionRuntime(
            model=AsyncFakeChatModel(AIMessage(content="done")), server_epoch="epoch-1"
        ).prompt(config, content="hello", message_id="user-1")

    asyncio.run(scenario())

    assert {event.phase for event in events} == {"before_model", "after_model"}
    assert all(event.thread_id == "hook-session" for event in events)
    assert all(event.run_id == "run-42" for event in events)
