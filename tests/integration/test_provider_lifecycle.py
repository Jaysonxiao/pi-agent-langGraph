"""Red tests for the learner-owned M9.2 Provider run lifecycle hooks."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import NodeCancelledError

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import stream_provider_session
from pi_agent.extensions import HookEvent, HookRegistry
from pi_agent.models import AsyncFakeChatModel


def _options(tmp_path: Path, *, session_id: str = "m92-thread") -> ProviderCliOptions:
    return ProviderCliOptions(
        provider="fake",
        prompt="read probe.txt and summarize",
        events="jsonl",
        database=tmp_path / "m92.sqlite",
        session_id=session_id,
        workspace=tmp_path,
    )


def _capture(registry: HookRegistry) -> list[HookEvent]:
    events: list[HookEvent] = []

    async def record(event: HookEvent) -> None:
        events.append(event)

    registry.register("capture", record)
    return events


def _run_events(events: list[HookEvent]) -> list[HookEvent]:
    return [event for event in events if event.phase in {"run_start", "run_end"}]


def test_run_lifecycle_correlates_each_completed_provider_run(tmp_path: Path) -> None:
    options = _options(tmp_path)
    registry = HookRegistry()
    events = _capture(registry)

    async def scenario() -> None:
        for index in range(2):
            async for _event in stream_provider_session(
                replace(options, prompt=f"turn {index}"),
                model=AsyncFakeChatModel(AIMessage(content="done", id=f"assistant-{index}")),
                message_id=f"user-{index}",
                hooks=registry,
            ):
                pass

    asyncio.run(scenario())

    events = _run_events(events)
    assert [event.phase for event in events] == ["run_start", "run_end"] * 2
    first_start, first_end, second_start, second_end = events
    assert first_start.thread_id == first_end.thread_id == options.session_id
    assert second_start.thread_id == second_end.thread_id == options.session_id
    assert first_start.run_id == first_end.run_id
    assert second_start.run_id == second_end.run_id
    assert first_start.run_id != second_start.run_id
    assert first_start.sequence < first_end.sequence
    assert second_start.sequence < second_end.sequence
    assert first_end.outcome == second_end.outcome == "completed"


def test_run_end_reports_graph_failed_state(tmp_path: Path) -> None:
    registry = HookRegistry()
    events = _capture(registry)

    async def scenario() -> None:
        async for _event in stream_provider_session(
            _options(tmp_path),
            model=AsyncFakeChatModel(error=RuntimeError("synthetic model failure")),
            message_id="user-failure",
            hooks=registry,
        ):
            pass

    asyncio.run(scenario())

    events = _run_events(events)
    assert [event.phase for event in events] == ["run_start", "run_end"]
    assert events[-1].outcome == "failed"
    assert events[0].run_id == events[-1].run_id


def test_run_end_reports_cancellation_and_propagates_it(tmp_path: Path) -> None:
    registry = HookRegistry()
    events = _capture(registry)

    async def scenario() -> None:
        async for _event in stream_provider_session(
            _options(tmp_path),
            model=AsyncFakeChatModel(error=asyncio.CancelledError()),
            message_id="user-cancelled",
            hooks=registry,
        ):
            pass

    with pytest.raises(NodeCancelledError):
        asyncio.run(scenario())

    events = _run_events(events)
    assert [event.phase for event in events] == ["run_start", "run_end"]
    assert events[-1].outcome == "cancelled"
    assert events[0].run_id == events[-1].run_id


def test_consumer_close_dispatches_one_cancelled_run_end(tmp_path: Path) -> None:
    registry = HookRegistry()
    events = _capture(registry)

    async def scenario() -> None:
        stream = stream_provider_session(
            _options(tmp_path),
            model=AsyncFakeChatModel(AIMessage(content="done", id="assistant-close")),
            message_id="user-close",
            hooks=registry,
        )
        await anext(stream)
        await stream.aclose()

    asyncio.run(scenario())

    events = _run_events(events)
    assert [event.phase for event in events] == ["run_start", "run_end"]
    assert events[-1].outcome == "cancelled"
    assert events[0].run_id == events[-1].run_id
