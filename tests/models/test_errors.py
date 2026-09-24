"""M8.4 error normalization remains safe for retry classification."""

from pi_agent.models.errors import ModelProviderError
from pi_agent.runtime.policy import classify_model_error


def test_normalized_provider_call_failure_is_retryable() -> None:
    assert (
        classify_model_error(ModelProviderError("provider_call_failed", "TimeoutError")) == "retry"
    )


def test_invalid_provider_response_is_not_retryable() -> None:
    assert classify_model_error(ModelProviderError("invalid_response", "dict")) == "stop"
