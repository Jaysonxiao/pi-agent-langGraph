"""Red tests for the learner-owned M9.3.2 async tool lifecycle hooks."""

import asyncio
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeCancelledError

import pi_agent.cli.runtime as provider_runtime
from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import stream_provider_session
from pi_agent.extensions import HookEvent, HookRegistry
from pi_agent.tools.async_registry import AsyncToolRegistry


class ScriptedAsyncModel:
    """Return one prepared model reply per call, including a tool call if requested."""

    def __init__(self, replies: Sequence[AIMessage]) -> None:
        self._replies = list(replies)

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        del messages, config
        return self._replies.pop(0)


def _options(tmp_path: Path, prompt: str) -> ProviderCliOptions:
    return ProviderCliOptions(
        provider="fake",
        prompt=prompt,
        events="jsonl",
        database=tmp_path / "m932.sqlite",
        session_id="m932-thread",
        workspace=tmp_path,
    )


def _capture(registry: HookRegistry) -> list[HookEvent]:
    events: list[HookEvent] = []

    async def record(event: HookEvent) -> None:
        events.append(event)

    registry.register("capture", record)
    return events


def _read_call(tool_name: str = "read", call_id: str = "read-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool_name,
                "args": {"path": "probe.txt"},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def test_tool_hooks_correlate_successful_tool_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "probe.txt").write_text("synthetic probe contents", encoding="utf-8")
    registry = HookRegistry()
    events = _capture(registry)
    model = ScriptedAsyncModel((_read_call(), AIMessage(content="summary", id="assistant-final")))

    async def scenario() -> None:
        async for _event in stream_provider_session(
            _options(tmp_path, "read probe.txt and summarize"),
            model=model,
            message_id="user-read",
            hooks=registry,
        ):
            pass

    asyncio.run(scenario())

    assert [event.phase for event in events] == [
        "run_start",
        "before_model",
        "after_model",
        "before_tool",
        "after_tool",
        "before_model",
        "after_model",
        "run_end",
    ]
    before_tool, after_tool = events[3:5]
    assert before_tool.thread_id == after_tool.thread_id == "m932-thread"
    assert before_tool.run_id == after_tool.run_id == events[0].run_id
    assert before_tool.sequence < after_tool.sequence
    assert before_tool.node == after_tool.node == "tools"
    assert before_tool.tool_name == after_tool.tool_name == "read"
    assert before_tool.tool_call_id == after_tool.tool_call_id == "read-1"
    assert after_tool.outcome == "completed"
    assert "synthetic probe contents" not in repr(events)
    assert "probe.txt" not in repr(events)
    assert all(earlier.sequence < later.sequence for earlier, later in pairwise(events))


def test_tool_hooks_report_unknown_tool_without_exposing_arguments(tmp_path: Path) -> None:
    registry = HookRegistry()
    events = _capture(registry)
    model = ScriptedAsyncModel(
        (
            _read_call(tool_name="missing", call_id="missing-1"),
            AIMessage(content="tool unavailable"),
        )
    )

    async def scenario() -> None:
        async for _event in stream_provider_session(
            _options(tmp_path, "call the missing tool with private arguments"),
            model=model,
            message_id="user-missing-tool",
            hooks=registry,
        ):
            pass

    asyncio.run(scenario())

    before_tool, after_tool = [
        event for event in events if event.phase in {"before_tool", "after_tool"}
    ]
    assert before_tool.phase == "before_tool"
    assert after_tool.phase == "after_tool"
    assert before_tool.tool_name == after_tool.tool_name == "missing"
    assert before_tool.tool_call_id == after_tool.tool_call_id == "missing-1"
    assert after_tool.outcome == "failed"
    assert "private arguments" not in repr(events)
    assert '"path"' not in repr(events)


class CancellingTool:
    @property
    def name(self) -> str:
        return "read"

    async def ainvoke(self, raw_args: Mapping[str, object]) -> str:
        del raw_args
        raise asyncio.CancelledError


def test_tool_hooks_report_and_propagate_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def cancelling_registry(
        *_args: object, **_kwargs: object
    ) -> tuple[AsyncToolRegistry, tuple[object, ...]]:
        return AsyncToolRegistry((CancellingTool(),)), ()

    monkeypatch.setattr(
        provider_runtime,
        "create_cli_async_read_only_registry",
        cancelling_registry,
    )
    registry = HookRegistry()
    events = _capture(registry)
    model = ScriptedAsyncModel((_read_call(),))

    async def scenario() -> None:
        async for _event in stream_provider_session(
            _options(tmp_path, "read probe.txt"),
            model=model,
            message_id="user-tool-cancel",
            hooks=registry,
        ):
            pass

    with pytest.raises(NodeCancelledError):
        asyncio.run(scenario())

    assert [event.phase for event in events] == [
        "run_start",
        "before_model",
        "after_model",
        "before_tool",
        "after_tool",
        "run_end",
    ]
    assert events[-2].outcome == "cancelled"
    assert events[-1].outcome == "cancelled"
