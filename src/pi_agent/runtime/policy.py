"""Pure retry policy and provider-error classification for M8.4."""

import math
from dataclasses import dataclass
from typing import Literal

from pi_agent.models.errors import ModelProviderError

RetryDisposition = Literal["retry", "stop"]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bound one model request by attempts, elapsed time, and backoff."""

    max_attempts: int = 3
    run_timeout_seconds: float = 120.0
    backoff_base_seconds: float = 0.5
    backoff_max_seconds: float = 8.0

    def __post_init__(self) -> None:
        """Reject ambiguous numeric values before a request starts."""
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer.")
        for name in (
            "run_timeout_seconds",
            "backoff_base_seconds",
            "backoff_max_seconds",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero.")
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError("backoff_max_seconds must not be below backoff_base_seconds.")


def classify_model_error(error: BaseException) -> RetryDisposition:
    """Classify normalized provider failures without inspecting secret text."""
    if isinstance(error, ModelProviderError):
        if error.status_code is not None:
            if error.status_code == 429 or 500 <= error.status_code <= 599:
                return "retry"
            return "stop"
        return "retry" if error.code == "provider_call_failed" else "stop"

    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        if status_code == 429 or 500 <= status_code <= 599:
            return "retry"
        if 400 <= status_code <= 499:
            return "stop"

    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return "retry"
    return "stop"


def retry_after_seconds(error: BaseException) -> float | None:
    """Read an optional numeric Retry-After value without reading exception text."""
    value = getattr(error, "retry_after_seconds", None)
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return float(value)
    return None
