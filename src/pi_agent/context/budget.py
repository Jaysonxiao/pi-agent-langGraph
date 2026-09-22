"""Deterministic message-budget boundaries for ephemeral model context."""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from langchain_core.messages import AnyMessage, SystemMessage

from pi_agent.context.messages import message_bytes, safe_boundaries


@dataclass(frozen=True, slots=True)
class BoundedContext:
    """Budgeted messages plus enough metadata for a context diagnostic."""

    messages: tuple[AnyMessage, ...]
    original_bytes: int
    kept_bytes: int
    dropped_messages: int
    max_bytes: int
    over_budget: bool


def fit_context_messages(
    messages: Sequence[AnyMessage],
    max_bytes: int,
) -> BoundedContext:
    """Keep system messages and the newest complete history messages."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer.")

    # 只读复制, 不改调用方的持久历史或装配结果.
    history = (*messages,)
    sizes = tuple(message_bytes(message) for message in history)
    original_bytes = sum(sizes)

    leading_system = 0
    for message in history:
        if not isinstance(message, SystemMessage):
            break
        leading_system += 1

    # 开头的规则必须整段保留; 即使自身超限也不拆, 只把 over_budget 标出来.
    system_messages = history[:leading_system]
    system_bytes = sum(sizes[:leading_system])
    rest = history[leading_system:]
    rest_sizes = sizes[leading_system:]

    boundaries = sorted(safe_boundaries(rest))
    start = len(rest)
    kept_bytes = system_bytes
    for left, right in reversed(list(pairwise(boundaries))):
        size = sum(rest_sizes[left:right])
        if kept_bytes + size > max_bytes:
            # 不拆消息, 也不跳过中间再捡更旧的短消息; 余下更旧的全部丢掉.
            break
        start = left
        kept_bytes += size

    kept_messages = (*system_messages, *rest[start:])
    return BoundedContext(
        messages=kept_messages,
        original_bytes=original_bytes,
        kept_bytes=kept_bytes,
        dropped_messages=len(history) - len(kept_messages),
        max_bytes=max_bytes,
        over_budget=kept_bytes > max_bytes,
    )
