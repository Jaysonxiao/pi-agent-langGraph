"""Red tests for the learner-owned M9.3.1 async model lifecycle hooks."""

import asyncio
from itertools import pairwise
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import NodeCancelledError

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import stream_provider_session
from pi_agent.extensions import HookEvent, HookRegistry
from pi_agent.models import AsyncFakeChatModel


def _options(tmp_path: Path, *, session_id: str = "m931-thread") -> ProviderCliOptions:
    return ProviderCliOptions(
        provider="fake",
        prompt="summarize probe.txt",
        events="jsonl",
        database=tmp_path / "m931.sqlite",
        session_id=session_id,
        workspace=tmp_path,
    )


def _capture(registry: HookRegistry) -> list[HookEvent]:
    events: list[HookEvent] = []

    async def record(event: HookEvent) -> None:
        events.append(event)

    registry.register("capture", record)
    return events


def test_model_hooks_are_ordered_and_correlated_on_success(tmp_path: Path) -> None:
    options = _options(tmp_path)
    registry = HookRegistry()
    events = _capture(registry)

    async def scenario() -> None:
        async for _event in stream_provider_session(
            options,
            model=AsyncFakeChatModel(AIMessage(content="summary", id="assistant-success")),
            message_id="user-success",
            hooks=registry,
        ):
            pass

    asyncio.run(scenario())

    assert [event.phase for event in events] == [
        "run_start",
        "before_model",
        "after_model",
        "run_end",
    ]
    assert {event.thread_id for event in events} == {options.session_id}
    assert len({event.run_id for event in events}) == 1
    assert all(earlier.sequence < later.sequence for earlier, later in pairwise(events))
    assert events[1].node == events[2].node == "model"
    assert events[2].outcome == "completed"
    assert events[-1].outcome == "completed"


def test_model_after_hook_reports_failure_without_model_payload(tmp_path: Path) -> None:
    registry = HookRegistry()
    events = _capture(registry)

    async def scenario() -> None:
        async for _event in stream_provider_session(
            _options(tmp_path),
            model=AsyncFakeChatModel(error=RuntimeError("Authorization: Bearer synthetic-secret")),
            message_id="user-failure",
            hooks=registry,
        ):
            pass

    asyncio.run(scenario())

    assert [event.phase for event in events] == [
        "run_start",
        "before_model",
        "after_model",
        "run_end",
    ]
    assert events[-2].outcome == "failed"
    assert events[-1].outcome == "failed"
    assert "synthetic-secret" not in repr(events)


def test_model_after_hook_reports_cancellation_and_propagates_it(tmp_path: Path) -> None:
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

    assert [event.phase for event in events] == [
        "run_start",
        "before_model",
        "after_model",
        "run_end",
    ]
    assert events[-2].outcome == "cancelled"
    assert events[-1].outcome == "cancelled"
