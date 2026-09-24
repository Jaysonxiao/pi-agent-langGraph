"""Red tests for the learner-owned M8.7-R3 async tool registry."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress

import pytest
from langchain_core.messages import ToolCall

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_registry import AsyncToolRegistry


class AsyncTool:
    """Small controllable async tool double for registry contracts."""

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


def test_async_registry_returns_correlated_success_message() -> None:
    async def handler(args: Mapping[str, object]) -> str:
        return f"read:{args['path']}"

    registry = AsyncToolRegistry([AsyncTool("read", handler)])

    result = asyncio.run(
        registry.execute_call(
            _call("read", {"path": "README.md"}, "call-read"),
            AsyncCancellationToken(),
        )
    )

    assert result.content == "read:README.md"
    assert result.tool_call_id == "call-read"
    assert result.id == "tool-result:call-read"
    assert result.name == "read"
    assert result.status == "success"


def test_pre_cancelled_token_does_not_start_async_tool() -> None:
    async def scenario() -> None:
        called = False

        async def handler(_: Mapping[str, object]) -> str:
            nonlocal called
            called = True
            return "unexpected"

        token = AsyncCancellationToken()
        token.cancel()
        registry = AsyncToolRegistry([AsyncTool("read", handler)])

        with pytest.raises(asyncio.CancelledError):
            await registry.execute_call(_call("read", {}, "call-cancelled"), token)

        assert not called

    asyncio.run(scenario())


def test_unknown_async_tool_returns_stable_error_message() -> None:
    result = asyncio.run(
        AsyncToolRegistry().execute_call(
            _call("missing", {}, "call-missing"),
            AsyncCancellationToken(),
        )
    )

    assert result.status == "error"
    assert _error_code(result.content) == "unknown_tool"
    assert result.tool_call_id == "call-missing"
    assert result.name == "missing"


def test_running_async_tool_is_cancelled_without_error_tool_message() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def handler(_: Mapping[str, object]) -> str:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
            return "unreachable"

        token = AsyncCancellationToken()
        registry = AsyncToolRegistry([AsyncTool("read", handler)])
        execution = asyncio.create_task(
            registry.execute_call(_call("read", {}, "call-running"), token)
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=0.1)
            token.cancel()

            with pytest.raises(asyncio.CancelledError):
                await execution

            assert cleaned.is_set()
        finally:
            if not execution.done():
                execution.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await execution

    asyncio.run(scenario())


def test_async_registry_projects_handler_error_like_sync_registry() -> None:
    async def handler(_: Mapping[str, object]) -> str:
        raise RuntimeError("controlled explosion")

    registry = AsyncToolRegistry([AsyncTool("explode", handler)])

    result = asyncio.run(
        registry.execute_call(_call("explode", {}, "call-error"), AsyncCancellationToken())
    )

    assert result.status == "error"
    assert _error_code(result.content) == "tool_execution_error"
    assert result.tool_call_id == "call-error"


def _call(name: str, args: dict[str, object], call_id: str) -> ToolCall:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _error_code(content: str | list[str | dict[object, object]]) -> object:
    assert isinstance(content, str)
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload.get("code")
