"""Plan safe history compaction without generating or persisting a summary."""

from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.messages import AnyMessage, SystemMessage

from pi_agent.context.messages import safe_boundaries


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """The stable prefix, removable history, and recent suffix of a context."""

    leading_system: tuple[AnyMessage, ...]
    removable: tuple[AnyMessage, ...]
    recent: tuple[AnyMessage, ...]


def plan_context_compaction(
    messages: Sequence[AnyMessage],
    keep_recent_messages: int,
) -> CompactionPlan:
    """Partition history for a later summary step without changing messages."""
    if keep_recent_messages <= 0:
        raise ValueError("keep_recent_messages must be a positive integer.")

    # 只划分引用, 不改消息对象, 也不在这里调用模型生成摘要.
    history = (*messages,)
    leading = 0
    for message in history:
        if not isinstance(message, SystemMessage):
            break
        leading += 1

    rest = history[leading:]
    start = _recent_start(rest, keep_recent_messages)
    return CompactionPlan(
        leading_system=history[:leading],
        removable=rest[:start],
        recent=rest[start:],
    )


def _recent_start(rest: tuple[AnyMessage, ...], keep_recent_messages: int) -> int:
    """Return the suffix index, expanding left so tool pairs stay intact."""
    start = max(0, len(rest) - keep_recent_messages)
    return max(boundary for boundary in safe_boundaries(rest) if boundary <= start)
