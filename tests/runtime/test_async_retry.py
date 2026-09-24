"""Red tests for the learner-owned M8.5-R4 native async retry loop."""

import asyncio
from dataclasses import dataclass

import pytest

from pi_agent.models.errors import ModelProviderError
from pi_agent.runtime import RetryExhausted, RetryPolicy, arun_with_retry


@dataclass
class AsyncFakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_async_transient_failure_retries_then_succeeds() -> None:
    clock = AsyncFakeClock()
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ModelProviderError("provider_call_failed", "TimeoutError")
        return "ok"

    result = asyncio.run(
        arun_with_retry(
            operation,
            RetryPolicy(max_attempts=3, backoff_base_seconds=0.5, backoff_max_seconds=8),
            clock=clock,
            sleep=clock.sleep,
        )
    )

    assert result == "ok"
    assert calls == 3
    assert clock.value == 1.5


def test_async_cancellation_propagates_without_a_retry_or_sleep() -> None:
    clock = AsyncFakeClock()
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(arun_with_retry(operation, RetryPolicy(), clock=clock, sleep=clock.sleep))

    assert calls == 1
    assert clock.value == 0.0


def test_async_deadline_prevents_sleeping_past_budget() -> None:
    clock = AsyncFakeClock()

    async def operation() -> str:
        raise TimeoutError()

    with pytest.raises(RetryExhausted, match="deadline_exceeded"):
        asyncio.run(
            arun_with_retry(
                operation,
                RetryPolicy(max_attempts=3, run_timeout_seconds=0.25),
                clock=clock,
                sleep=clock.sleep,
            )
        )

    assert clock.value == 0.0


def test_async_retry_after_is_capped_and_final_attempt_does_not_sleep() -> None:
    class RateLimited(RuntimeError):
        status_code = 429
        retry_after_seconds = 1.25

    clock = AsyncFakeClock()
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise RateLimited("provider detail")

    with pytest.raises(RetryExhausted) as raised:
        asyncio.run(
            arun_with_retry(
                operation,
                RetryPolicy(max_attempts=2, backoff_base_seconds=0.5, backoff_max_seconds=1.0),
                clock=clock,
                sleep=clock.sleep,
            )
        )

    assert raised.value.reason == "attempts_exhausted"
    assert calls == 2
    assert clock.value == 1.0
