"""Native asynchronous bounded retry for M8.5-R4."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pi_agent.runtime.policy import RetryPolicy, classify_model_error, retry_after_seconds
from pi_agent.runtime.retry import RetryExhausted, _backoff

ResultT = TypeVar("ResultT")
AsyncOperation = Callable[[], Awaitable[ResultT]]
Clock = Callable[[], float]
AsyncSleeper = Callable[[float], Awaitable[None]]
Jitter = Callable[[float], float]


async def arun_with_retry(
    operation: AsyncOperation[ResultT],
    policy: RetryPolicy,
    *,
    clock: Clock,
    sleep: AsyncSleeper,
    jitter: Jitter | None = None,
) -> ResultT:
    """Await one operation within the shared retry policy."""
    started_at = clock()
    attempts = 0
    deadline = started_at + policy.run_timeout_seconds

    while attempts < policy.max_attempts:
        # 进入下一次调用前若已超时, 不再调度 operation.
        if clock() >= deadline:
            raise RetryExhausted("deadline_exceeded", attempts)
        attempts += 1
        try:
            return await operation()
        except asyncio.CancelledError:
            # 取消必须原样传播: 不分类、不 sleep、不重试.
            raise
        except BaseException as exc:
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
            # delay 占满剩余预算则直接停, 避免 sleep 越过 deadline.
            if remaining <= 0 or delay >= remaining:
                raise RetryExhausted("deadline_exceeded", attempts) from None
            await sleep(delay)

    raise RetryExhausted("attempts_exhausted", attempts)
