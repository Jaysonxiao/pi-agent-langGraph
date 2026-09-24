"""Synchronous, bounded retry execution for one model operation."""

import asyncio
import math
import time
from collections.abc import Callable
from typing import TypeVar

from pi_agent.runtime.policy import RetryPolicy, classify_model_error, retry_after_seconds

ResultT = TypeVar("ResultT")
Clock = Callable[[], float]
Sleeper = Callable[[float], None]
Jitter = Callable[[float], float]


class RetryExhausted(RuntimeError):
    """Safe terminal result after a retry policy refuses further work."""

    def __init__(self, reason: str, attempts: int) -> None:
        self.reason = reason
        self.attempts = attempts
        super().__init__(f"Model retry stopped ({reason}) after {attempts} attempt(s).")


def run_with_retry(
    operation: Callable[[], ResultT],
    policy: RetryPolicy,
    *,
    clock: Clock = time.monotonic,
    sleep: Sleeper = time.sleep,
    jitter: Jitter | None = None,
) -> ResultT:
    """Run one operation until success, safe stop, attempt limit, or deadline."""
    started_at = clock()
    attempts = 0
    deadline = started_at + policy.run_timeout_seconds

    while attempts < policy.max_attempts:
        if clock() >= deadline:
            raise RetryExhausted("deadline_exceeded", attempts)
        attempts += 1
        try:
            return operation()
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            if classify_model_error(exc) == "stop":
                raise RetryExhausted("non_retryable", attempts) from None
            if attempts >= policy.max_attempts:
                raise RetryExhausted("attempts_exhausted", attempts) from None

            delay = _backoff(policy, attempts)
            retry_after = retry_after_seconds(exc)
            if retry_after is not None:
                delay = max(delay, retry_after)
            if jitter is not None:
                delay = jitter(delay)
            if not math.isfinite(delay) or delay < 0:
                raise RetryExhausted("invalid_backoff", attempts) from None
            delay = min(delay, policy.backoff_max_seconds)
            remaining = deadline - clock()
            if remaining <= 0 or delay >= remaining:
                raise RetryExhausted("deadline_exceeded", attempts) from None
            sleep(delay)

    raise RetryExhausted("attempts_exhausted", attempts)


def _backoff(policy: RetryPolicy, attempts: int) -> float:
    """Return the capped exponential delay after a failed attempt."""
    exponential = policy.backoff_base_seconds * float(2 ** (attempts - 1))
    return min(policy.backoff_max_seconds, exponential)
