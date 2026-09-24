"""Ownership boundary for a single cancellable asynchronous operation."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import TypeVar

from pi_agent.runtime.cancellation import AsyncCancellationToken

T = TypeVar("T")


async def run_cancellable(
    operation: Callable[[], Awaitable[T]],
    token: AsyncCancellationToken,
    /,
) -> T:
    """Run one owned operation and join it if the runtime is cancelled."""
    # 预先取消则零调用, 避免刚启动就立刻拆掉.
    token.raise_if_cancelled()

    async def owned() -> T:
        return await operation()

    op_task: asyncio.Task[T] = asyncio.create_task(owned())
    wait_task = asyncio.create_task(token.wait())
    try:
        await asyncio.wait({op_task, wait_task}, return_when=asyncio.FIRST_COMPLETED)
        if op_task.done() and not op_task.cancelled():
            # 成功值或普通异常都从 result() 原样冒出.
            return op_task.result()

        # token 先到或自身被取消: 真正的 cancel/join 交给 finally, 保证所有退出路径一致.
        raise asyncio.CancelledError()
    finally:
        # 无论成功、业务异常、token 取消还是外层取消, 自建 task 都不能遗留.
        if not wait_task.done():
            wait_task.cancel()
        with suppress(asyncio.CancelledError):
            await wait_task
        if not op_task.done():
            op_task.cancel()
        if not op_task.done() or op_task.cancelled():
            with suppress(asyncio.CancelledError):
                await op_task
