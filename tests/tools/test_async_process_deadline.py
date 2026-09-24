"""Red tests for learner-owned M8.7-R7 process deadline semantics."""

import asyncio
from contextlib import suppress

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_process import (
    AsyncSpawnedProcess,
    run_controlled_async_process,
)
from pi_agent.tools.process import ProcessArguments, ProcessExecutionError


class BlockingProcess(AsyncSpawnedProcess):
    """Process double that finishes only after lifecycle termination."""

    def __init__(self, *, block: bool) -> None:
        self._block = block
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.terminated = 0
        self.reaped = False

    async def communicate(self) -> tuple[str, str]:
        if self._block:
            self.started.set()
            await self.release.wait()
        self.reaped = True
        return ("stdout", "stderr")

    async def terminate_tree(self) -> None:
        self.terminated += 1
        self.release.set()


def test_async_process_returns_output_before_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    process = BlockingProcess(block=False)

    async def spawn(**_: object) -> AsyncSpawnedProcess:
        return process

    monkeypatch.setattr("pi_agent.tools.async_process.spawn_controlled_process", spawn)

    assert asyncio.run(_run(token=AsyncCancellationToken(), timeout_seconds=1)) == (
        "stdout",
        "stderr",
    )
    assert process.terminated == 0


def test_deadline_terminates_and_reaps_then_raises_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = BlockingProcess(block=True)

    async def spawn(**_: object) -> AsyncSpawnedProcess:
        return process

    monkeypatch.setattr("pi_agent.tools.async_process.spawn_controlled_process", spawn)

    with pytest.raises(ProcessExecutionError) as raised:
        asyncio.run(_run(token=AsyncCancellationToken(), timeout_seconds=0.01))

    assert raised.value.code == "timeout"
    assert process.terminated == 1
    assert process.reaped


def test_token_cancellation_is_not_reclassified_as_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        process = BlockingProcess(block=True)

        async def spawn(**_: object) -> AsyncSpawnedProcess:
            return process

        monkeypatch.setattr("pi_agent.tools.async_process.spawn_controlled_process", spawn)
        token = AsyncCancellationToken()
        execution = asyncio.create_task(_run(token=token, timeout_seconds=1))
        try:
            await asyncio.wait_for(process.started.wait(), timeout=0.1)
            token.cancel()

            with pytest.raises(asyncio.CancelledError):
                await execution

            assert process.terminated == 1
            assert process.reaped
        finally:
            if not execution.done():
                execution.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await execution

    asyncio.run(scenario())


async def _run(*, token: AsyncCancellationToken, timeout_seconds: float) -> tuple[str, str]:
    return await run_controlled_async_process(
        ProcessArguments(executable="allowed", argv=[], timeout_seconds=timeout_seconds),
        allowed_executables=frozenset({"allowed"}),
        cwd=".",
        token=token,
    )
