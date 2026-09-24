"""Red tests for the learner-owned M8.6-R3 usage normalization and ledger."""

import pytest

from pi_agent.models.usage import TokenUsage, UsageLedger, normalize_usage


def test_normalize_provider_usage_and_reject_inconsistent_total() -> None:
    usage = normalize_usage({"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})

    assert usage == TokenUsage(5, 3, 8, "provider")

    with pytest.raises(ValueError, match="usage"):
        normalize_usage({"input_tokens": 5, "output_tokens": 3, "total_tokens": 7})


def test_missing_usage_is_unknown_not_zero() -> None:
    assert normalize_usage(None) == TokenUsage(None, None, None, "unknown")
    assert normalize_usage({}) == TokenUsage(None, None, None, "unknown")


def test_ledger_deduplicates_one_logical_attempt_and_sums_distinct_attempts() -> None:
    ledger = UsageLedger()

    first = ledger.record_final(
        "main:1", {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
    )
    duplicate = ledger.record_final(
        "main:1", {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
    )
    second = ledger.record_final(
        "summary:1", {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    )

    assert duplicate is first
    assert second == TokenUsage(2, 1, 3, "provider")
    assert ledger.total() == TokenUsage(7, 4, 11, "provider")


def test_ledger_rejects_conflicting_or_secret_shaped_usage() -> None:
    ledger = UsageLedger()
    ledger.record_final("main:1", {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})

    with pytest.raises(ValueError, match="attempt"):
        ledger.record_final("main:1", {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})

    secret = "usage-secret-value"
    with pytest.raises(ValueError, match="usage") as raised:
        ledger.record_final("main:2", {"input_tokens": secret})

    assert secret not in str(raised.value)
