"""Message sizing and protocol boundaries shared by context transformations."""

import json
from collections.abc import Sequence

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage


def encoded_size(value: object) -> int:
    """Measure text or JSON content, rejecting unsupported values explicitly."""
    text = (
        value
        if isinstance(value, str)
        else json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    )
    return len(text.encode())


def message_bytes(message: AnyMessage) -> int:
    """Include model-visible tool arguments and result correlation in the size."""
    size = encoded_size(message.content)
    if isinstance(message, AIMessage) and message.tool_calls:
        size += encoded_size(message.tool_calls)
    if isinstance(message, ToolMessage):
        size += encoded_size(message.tool_call_id)
    return size


def context_bytes(messages: Sequence[AnyMessage]) -> int:
    return sum(message_bytes(message) for message in messages)


def estimate_tokens(messages: Sequence[AnyMessage]) -> int:
    """Deterministic heuristic: ceil(UTF-8 bytes / 4) + 4 framing tokens/message.

    This is a scheduling estimate, not a tokenizer or provider billing count.
    Image/audio resource contents are not fetched or measured.
    """
    return sum((message_bytes(message) + 3) // 4 + 4 for message in messages)


def safe_boundaries(messages: Sequence[AnyMessage]) -> frozenset[int]:
    """Return cut points at which no tool call is awaiting a correlated result."""
    pending: set[str] = set()
    boundaries = {0}
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            if message.tool_call_id not in pending:
                raise ValueError("Tool result has no pending matching call.")
            pending.remove(message.tool_call_id)
        else:
            if pending:
                raise ValueError("Tool calls must receive all results before another message.")
            if isinstance(message, AIMessage) and message.tool_calls:
                ids = [call["id"] for call in message.tool_calls]
                if any(not call_id for call_id in ids) or len(set(ids)) != len(ids):
                    raise ValueError("Tool call IDs must be nonempty and unique within a batch.")
                pending.update(call_id for call_id in ids if call_id is not None)
        if not pending:
            boundaries.add(index + 1)
    if pending:
        raise ValueError("Context ends with unresolved tool calls.")
    return frozenset(boundaries)
