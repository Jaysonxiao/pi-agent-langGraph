"""Provider usage normalization without turning missing data into zero."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

UsageSource = Literal["provider", "unknown"]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """One logical model attempt's token counters, never a cost estimate."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    source: UsageSource


def normalize_usage(metadata: Mapping[str, object] | None, /) -> TokenUsage:
    """Normalize standard provider usage metadata into explicit known/unknown fields."""
    if metadata is None:
        return TokenUsage(None, None, None, "unknown")

    input_tokens = _optional_count(metadata, "input_tokens")
    output_tokens = _optional_count(metadata, "output_tokens")
    total_tokens = _optional_count(metadata, "total_tokens")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return TokenUsage(None, None, None, "unknown")
    # 三项都给出时 total 必须等于 input+output; 错误文本不含具体数字.
    if (
        input_tokens is not None
        and output_tokens is not None
        and total_tokens is not None
        and total_tokens != input_tokens + output_tokens
    ):
        raise ValueError("usage totals are inconsistent")
    return TokenUsage(input_tokens, output_tokens, total_tokens, "provider")


def _optional_count(metadata: Mapping[str, object], field: str) -> int | None:
    """Accept a missing field as unknown; reject bools, floats, and negatives."""
    if field not in metadata:
        return None
    value = metadata[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("usage field is malformed")
    return value


class UsageLedger:
    """Keep one final usage record per logical model attempt."""

    def __init__(self) -> None:
        self._by_attempt: dict[str, TokenUsage] = {}

    def record_final(
        self,
        attempt_id: str,
        metadata: Mapping[str, object] | None,
        /,
    ) -> TokenUsage:
        """Normalize once; equal duplicates return the stored record, conflicts fail."""
        usage = normalize_usage(metadata)
        existing = self._by_attempt.get(attempt_id)
        if existing is None:
            self._by_attempt[attempt_id] = usage
            return usage
        if existing != usage:
            raise ValueError("attempt usage conflict")
        return existing

    def total(self) -> TokenUsage:
        """Sum a field only when every recorded attempt has that field known."""
        records = tuple(self._by_attempt.values())
        if not records:
            return TokenUsage(None, None, None, "unknown")
        input_tokens = _sum_known(records, "input_tokens")
        output_tokens = _sum_known(records, "output_tokens")
        total_tokens = _sum_known(records, "total_tokens")
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return TokenUsage(None, None, None, "unknown")
        return TokenUsage(input_tokens, output_tokens, total_tokens, "provider")


def _sum_known(records: tuple[TokenUsage, ...], field: str) -> int | None:
    """Return None unless every attempt recorded a concrete count for ``field``."""
    values: list[int] = []
    for record in records:
        value = getattr(record, field)
        if not isinstance(value, int):
            return None
        values.append(value)
    return sum(values)
