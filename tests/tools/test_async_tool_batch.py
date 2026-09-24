"""Red tests for learner-owned M8.7-R4 batch cancellation accounting."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress

import pytest
from langchain_core.messages import ToolCall

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_registry import AsyncToolBatchCancelled, AsyncToolRegistry


class AsyncTool:
    """Controllable async tool double for sequential batch contracts."""

    def __init__(
        self,
        name: str,
        handler: Callable[[Mapping[str, object]], Awaitable[str]],
    ) -> None:
        self._name = name
        self._handler = handler

    @property
    def name(self) -> str:
        return self._name

    async def ainvoke(self, raw_args: Mapping[str, object]) -> str:
        return await self._handler(raw_args)


def test_batch_executes_calls_in_source_order() -> None:
    calls: list[str] = []

    async def handler(args: Mapping[str, object]) -> str:
        value = str(args["value"])
        calls.append(value)
        return value

    registry = AsyncToolRegistry([AsyncTool("record", handler)])

    results = asyncio.run(
        registry.execute_calls(
            (
                _call("record", {"value": "first"}, "call-1"),
                _call("record", {"value": "second"}, "call-2"),
            ),
            AsyncCancellationToken(),
        )
    )

    assert calls == ["first", "second"]
    assert [result.content for result in results] == ["first", "second"]
    assert [result.tool_call_id for result in results] == ["call-1", "call-2"]


def test_pre_cancelled_batch_records_every_call_as_unstarted() -> None:
    async def handler(_: Mapping[str, object]) -> str:
        raise AssertionError("pre-cancelled batch must not start a handler")

    token = AsyncCancellationToken()
    token.cancel()
    registry = AsyncToolRegistry([AsyncTool("record", handler)])

    with pytest.raises(AsyncToolBatchCancelled) as raised:
        asyncio.run(
            registry.execute_calls(
                (_call("record", {}, "call-1"), _call("record", {}, "call-2")),
                token,
            )
        )

    assert raised.value.completed == ()
    assert raised.value.interrupted_call_id is None
    assert raised.value.unstarted_call_ids == ("call-1", "call-2")


def test_cancelled_running_call_is_unknown_and_later_calls_are_unstarted() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cleaned = asyncio.Event()
        later_started = False

        async def first(_: Mapping[str, object]) -> str:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
            return "unreachable"

        async def second(_: Mapping[str, object]) -> str:
            nonlocal later_started
            later_started = True
            return "unexpected"

        token = AsyncCancellationToken()
        registry = AsyncToolRegistry([AsyncTool("first", first), AsyncTool("second", second)])
        execution = asyncio.create_task(
            registry.execute_calls(
                (_call("first", {}, "call-1"), _call("second", {}, "call-2")),
                token,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=0.1)
            token.cancel()

            with pytest.raises(AsyncToolBatchCancelled) as raised:
                await execution

            assert raised.value.completed == ()
            assert raised.value.interrupted_call_id == "call-1"
            assert raised.value.unstarted_call_ids == ("call-2",)
            assert cleaned.is_set()
            assert not later_started
        finally:
            if not execution.done():
                execution.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await execution

    asyncio.run(scenario())


def test_completed_call_is_retained_when_next_call_is_not_started() -> None:
    async def scenario() -> None:
        token = AsyncCancellationToken()
        later_started = False

        async def first(_: Mapping[str, object]) -> str:
            token.cancel()
            return "first-result"

        async def second(_: Mapping[str, object]) -> str:
            nonlocal later_started
            later_started = True
            return "unexpected"

        registry = AsyncToolRegistry([AsyncTool("first", first), AsyncTool("second", second)])

        with pytest.raises(AsyncToolBatchCancelled) as raised:
            await registry.execute_calls(
                (_call("first", {}, "call-1"), _call("second", {}, "call-2")),
                token,
            )

        assert [result.content for result in raised.value.completed] == ["first-result"]
        assert raised.value.interrupted_call_id is None
        assert raised.value.unstarted_call_ids == ("call-2",)
        assert not later_started

    asyncio.run(scenario())


def _call(name: str, args: dict[str, object], call_id: str) -> ToolCall:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}
