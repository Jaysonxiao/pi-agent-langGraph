"""Red tests for the learner-owned M8.7-R2 task ownership boundary."""

import asyncio
from contextlib import suppress

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.runner import run_cancellable


def test_pre_cancelled_token_does_not_start_operation() -> None:
    async def scenario() -> None:
        token = AsyncCancellationToken()
        started = False

        async def operation() -> str:
            nonlocal started
            started = True
            return "unexpected"

        token.cancel()

        with pytest.raises(asyncio.CancelledError):
            await run_cancellable(operation, token)

        assert not started

    asyncio.run(scenario())


def test_running_operation_is_cancelled_and_joined_before_returning() -> None:
    async def scenario() -> None:
        token = AsyncCancellationToken()
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def operation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        runner = asyncio.create_task(run_cancellable(operation, token))
        try:
            await asyncio.wait_for(started.wait(), timeout=0.1)
            token.cancel()

            with pytest.raises(asyncio.CancelledError):
                await runner

            assert cleaned.is_set()
        finally:
            if not runner.done():
                runner.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await runner

    asyncio.run(scenario())


def test_cancelling_runner_also_cancels_and_joins_owned_operation() -> None:
    async def scenario() -> None:
        token = AsyncCancellationToken()
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def operation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        runner = asyncio.create_task(run_cancellable(operation, token))
        await asyncio.wait_for(started.wait(), timeout=0.1)
        runner.cancel()

        with pytest.raises(asyncio.CancelledError):
            await runner

        assert cleaned.is_set()

    asyncio.run(scenario())


def test_successful_operation_returns_its_value() -> None:
    async def operation() -> str:
        return "complete"

    assert asyncio.run(run_cancellable(operation, AsyncCancellationToken())) == "complete"
