"""Asynchronous tool registry with cancellation-aware task ownership."""

import asyncio
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import ToolCall, ToolMessage

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.runner import run_cancellable
from pi_agent.tools.base import ToolArgumentError
from pi_agent.tools.registry import (
    _require_call_id,
    _tool_result_message_id,
    create_error_tool_message,
)


class AsyncExecutableTool(Protocol):
    """Minimal asynchronous tool port needed by the runtime registry."""

    @property
    def name(self) -> str:
        """Return the model-visible unique tool name."""
        ...

    def ainvoke(self, raw_args: Mapping[str, object]) -> Awaitable[str]:
        """Validate and execute one asynchronous tool call."""
        ...


@dataclass(frozen=True, slots=True)
class AsyncToolBatchCancelled(asyncio.CancelledError):
    """Native cancellation enriched with facts for the batch caller."""

    completed: tuple[ToolMessage, ...]
    interrupted_call_id: str | None
    unstarted_call_ids: tuple[str, ...]


class AsyncToolRegistry:
    """Stable async lookup table; one call is owned by one runner."""

    def __init__(self, tools: Iterable[AsyncExecutableTool] = ()) -> None:
        registered: dict[str, AsyncExecutableTool] = {}
        for tool in tools:
            if tool.name in registered:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            registered[tool.name] = tool
        self._tools = registered

    def find(self, name: str) -> AsyncExecutableTool | None:
        """Return a registered async tool without exposing mutable storage."""
        return self._tools.get(name)

    async def execute_call(
        self,
        tool_call: ToolCall,
        token: AsyncCancellationToken,
        /,
    ) -> ToolMessage:
        """Execute one complete tool call or propagate runtime cancellation."""
        tool = self.find(tool_call["name"])
        if tool is None:
            # 未知工具是模型可见错误, 不进入 runner, 也不算取消.
            return create_error_tool_message(
                tool_call,
                code="unknown_tool",
                message=f"Unknown tool: {tool_call['name']}",
            )

        try:
            # 单次 ainvoke 交给 runner 拥有; 预取消零调用, 运行中取消不投影 ToolMessage.
            content = await run_cancellable(
                lambda: tool.ainvoke(tool_call["args"]),
                token,
            )
        except ToolArgumentError as exc:
            return create_error_tool_message(
                tool_call,
                code="invalid_arguments",
                message=str(exc),
                details=exc.details,
            )
        except Exception as exc:
            # CancelledError 不是 Exception, 会原样冒泡出工具边界.
            return create_error_tool_message(
                tool_call,
                code="tool_execution_error",
                message=str(exc),
            )

        call_id = _require_call_id(tool_call)
        return ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=tool_call["name"],
            status="success",
            id=_tool_result_message_id(call_id),
        )

    async def execute_calls(
        self,
        tool_calls: Iterable[ToolCall],
        token: AsyncCancellationToken,
        /,
    ) -> tuple[ToolMessage, ...]:
        """Execute calls in source order or report a cancellation audit."""
        pending = tuple(tool_calls)
        completed: list[ToolMessage] = []
        for index, tool_call in enumerate(pending):
            # 开始下一项之前看 token: 已取消则当前项也从未启动.
            if token.cancelled:
                raise AsyncToolBatchCancelled(
                    completed=tuple(completed),
                    interrupted_call_id=None,
                    unstarted_call_ids=tuple(_require_call_id(call) for call in pending[index:]),
                )
            try:
                completed.append(await self.execute_call(tool_call, token))
            except asyncio.CancelledError:
                # handler 的 finally 已由 execute_call/runner join; 不伪造执行中结果.
                raise AsyncToolBatchCancelled(
                    completed=tuple(completed),
                    interrupted_call_id=_require_call_id(tool_call),
                    unstarted_call_ids=tuple(
                        _require_call_id(call) for call in pending[index + 1 :]
                    ),
                ) from None
        return tuple(completed)
