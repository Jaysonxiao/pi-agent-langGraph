"""Red tests for M8.7-R10 wiring R5 lifecycle to R9 tree termination."""

import asyncio

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_process import AsyncSpawnedProcess, run_spawned_process


class TreeAwareProcess(AsyncSpawnedProcess):
    """Fake process that records tree termination before final reap."""

    def __init__(self, *, block: bool) -> None:
        self._block = block
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.events: list[str] = []

    async def communicate(self) -> tuple[str, str]:
        self.events.append("communicate")
        if self._block and len(self.events) == 1:
            self.started.set()
            await self.release.wait()
        return ("stdout", "stderr")

    async def terminate_tree(self) -> None:
        self.events.append("terminate_tree")
        self.release.set()

    def terminate(self) -> None:
        raise AssertionError("R10 must use terminate_tree")


def test_cancel_uses_tree_aware_termination_before_reap() -> None:
    async def scenario() -> None:
        process = TreeAwareProcess(block=True)

        async def spawn() -> AsyncSpawnedProcess:
            return process

        token = AsyncCancellationToken()
        execution = asyncio.create_task(run_spawned_process(spawn, token))
        await asyncio.wait_for(process.started.wait(), timeout=0.1)
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            await execution

        assert process.events == ["communicate", "terminate_tree", "communicate"]

    asyncio.run(scenario())


def test_normal_completion_does_not_terminate_tree() -> None:
    process = TreeAwareProcess(block=False)

    async def spawn() -> AsyncSpawnedProcess:
        return process

    assert asyncio.run(run_spawned_process(spawn, AsyncCancellationToken())) == (
        "stdout",
        "stderr",
    )
    assert process.events == ["communicate"]


def test_external_runner_cancellation_also_uses_tree_termination() -> None:
    async def scenario() -> None:
        process = TreeAwareProcess(block=True)

        async def spawn() -> AsyncSpawnedProcess:
            return process

        execution = asyncio.create_task(run_spawned_process(spawn, AsyncCancellationToken()))
        try:
            await asyncio.wait_for(process.started.wait(), timeout=0.1)
            execution.cancel()

            with pytest.raises(asyncio.CancelledError):
                await execution

            assert process.events == ["communicate", "terminate_tree", "communicate"]
        finally:
            if not execution.done():
                execution.cancel()
            with pytest.raises((asyncio.CancelledError, AttributeError, NotImplementedError)):
                await execution

    asyncio.run(scenario())
