"""M8.4 bounded retry behavior with deterministic time dependencies."""

from dataclasses import dataclass

import pytest

from pi_agent.models.errors import ModelProviderError
from pi_agent.runtime import RetryExhausted, RetryPolicy, run_with_retry


@dataclass
class FakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_transient_provider_failure_retries_and_returns_success() -> None:
    calls = 0
    clock = FakeClock()

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ModelProviderError("provider_call_failed", "TimeoutError")
        return "ok"

    result = run_with_retry(
        operation,
        RetryPolicy(max_attempts=3, backoff_base_seconds=0.5, backoff_max_seconds=8),
        clock=clock,
        sleep=clock.sleep,
    )

    assert result == "ok"
    assert calls == 3
    assert clock.value == 1.5


def test_non_retryable_failure_is_called_once_and_hides_exception_text() -> None:
    calls = 0

    def operation() -> str:
        nonlocal calls
        calls += 1
        raise ValueError("Authorization: Bearer synthetic-secret")

    with pytest.raises(RetryExhausted) as raised:
        run_with_retry(operation, RetryPolicy())

    assert calls == 1
    assert raised.value.reason == "non_retryable"
    assert "synthetic-secret" not in str(raised.value)


def test_retry_after_is_capped_and_last_attempt_does_not_sleep() -> None:
    class RateLimited(RuntimeError):
        status_code = 429
        retry_after_seconds = 1.25

    calls = 0
    clock = FakeClock()

    def operation() -> str:
        nonlocal calls
        calls += 1
        raise RateLimited("provider details")

    with pytest.raises(RetryExhausted) as raised:
        run_with_retry(
            operation,
            RetryPolicy(max_attempts=2, backoff_base_seconds=0.5, backoff_max_seconds=1.0),
            clock=clock,
            sleep=clock.sleep,
        )

    assert calls == 2
    assert raised.value.reason == "attempts_exhausted"
    assert clock.value == 1.0


def test_deadline_prevents_sleeping_past_budget() -> None:
    clock = FakeClock()

    with pytest.raises(RetryExhausted, match="deadline_exceeded"):
        run_with_retry(
            lambda: (_ for _ in ()).throw(TimeoutError()),
            RetryPolicy(max_attempts=3, run_timeout_seconds=0.25),
            clock=clock,
            sleep=clock.sleep,
        )

    assert clock.value == 0.0
