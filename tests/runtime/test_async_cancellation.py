"""Red tests for the learner-owned M8.7-R1 async cancellation token."""

import asyncio
from contextlib import suppress

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken


def test_async_token_is_initially_open_then_idempotently_cancelled() -> None:
    token = AsyncCancellationToken()

    assert not token.cancelled
    token.cancel()
    token.cancel()

    assert token.cancelled


def test_async_token_waits_without_polling_until_cancelled() -> None:
    async def wait_then_cancel() -> bool:
        token = AsyncCancellationToken()
        waiter = asyncio.create_task(token.wait())
        try:
            await asyncio.sleep(0)
            assert not waiter.done()
            token.cancel()
            await waiter
            return token.cancelled
        finally:
            if not waiter.done():
                waiter.cancel()
            with suppress(asyncio.CancelledError, NotImplementedError):
                await waiter

    assert asyncio.run(wait_then_cancel())


def test_async_token_raises_native_cancellation_only_after_request() -> None:
    token = AsyncCancellationToken()

    token.raise_if_cancelled()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        token.raise_if_cancelled()
