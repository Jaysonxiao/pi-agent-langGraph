"""Red tests for learner-owned M8.7-R5 spawned-process lifetime handling."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools import async_process
from pi_agent.tools.async_process import AsyncSpawnedProcess, run_spawned_process


class FakeProcess(AsyncSpawnedProcess):
    """In-memory process double whose first wait may be held open."""

    def __init__(self, *, block_first_wait: bool) -> None:
        self._block_first_wait = block_first_wait
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.terminate_calls = 0
        self.communicate_calls = 0
        self.reaped = False

    async def communicate(self) -> tuple[str, str]:
        self.communicate_calls += 1
        if self._block_first_wait and self.communicate_calls == 1:
            self.started.set()
            await self.release.wait()
        self.reaped = True
        return ("stdout", "stderr")

    async def terminate_tree(self) -> None:
        self.terminate_calls += 1
        self.release.set()


def test_pre_cancelled_token_does_not_spawn_process() -> None:
    async def scenario() -> None:
        spawned = False

        async def spawn() -> AsyncSpawnedProcess:
            nonlocal spawned
            spawned = True
            return FakeProcess(block_first_wait=False)

        token = AsyncCancellationToken()
        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            await run_spawned_process(spawn, token)

        assert not spawned

    asyncio.run(scenario())


def test_successful_process_returns_communicated_output_without_termination() -> None:
    process = FakeProcess(block_first_wait=False)

    async def spawn() -> AsyncSpawnedProcess:
        return process

    assert asyncio.run(run_spawned_process(spawn, AsyncCancellationToken())) == (
        "stdout",
        "stderr",
    )
    assert process.terminate_calls == 0
    assert process.communicate_calls == 1
    assert process.reaped


def test_process_lifecycle_delegates_task_ownership_to_runtime_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = FakeProcess(block_first_wait=False)
    runner_calls = 0

    async def spawn() -> AsyncSpawnedProcess:
        return process

    async def recording_runner(
        operation: Callable[[], Awaitable[tuple[str, str]]],
        token: AsyncCancellationToken,
    ) -> tuple[str, str]:
        nonlocal runner_calls
        runner_calls += 1
        return await operation()

    monkeypatch.setattr(async_process, "run_cancellable", recording_runner, raising=False)

    assert asyncio.run(run_spawned_process(spawn, AsyncCancellationToken())) == (
        "stdout",
        "stderr",
    )
    assert runner_calls == 1


def test_token_cancellation_terminates_and_reaps_spawned_process() -> None:
    async def scenario() -> None:
        process = FakeProcess(block_first_wait=True)

        async def spawn() -> AsyncSpawnedProcess:
            return process

        token = AsyncCancellationToken()
        execution = asyncio.create_task(run_spawned_process(spawn, token))
        try:
            await asyncio.wait_for(process.started.wait(), timeout=0.1)
            token.cancel()

            with pytest.raises(asyncio.CancelledError):
                await execution

            assert process.terminate_calls == 1
            assert process.communicate_calls == 2
            assert process.reaped
        finally:
            if not execution.done():
                execution.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await execution

    asyncio.run(scenario())


def test_outer_cancellation_terminates_and_reaps_spawned_process() -> None:
    async def scenario() -> None:
        process = FakeProcess(block_first_wait=True)

        async def spawn() -> AsyncSpawnedProcess:
            return process

        execution = asyncio.create_task(run_spawned_process(spawn, AsyncCancellationToken()))
        try:
            await asyncio.wait_for(process.started.wait(), timeout=0.1)
            execution.cancel()

            with pytest.raises(asyncio.CancelledError):
                await execution

            assert process.terminate_calls == 1
            assert process.communicate_calls == 2
            assert process.reaped
        finally:
            if not execution.done():
                execution.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await execution

    asyncio.run(scenario())
