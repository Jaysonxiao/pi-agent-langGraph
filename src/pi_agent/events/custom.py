"""Projection of LangGraph custom-stream chunks into stable progress events."""

from collections.abc import Mapping

from pi_agent.events.stream import StreamEvent


def _require_non_empty_str(chunk: Mapping[str, object], field_name: str) -> str:
    """node/message 必须由 writer 显式给出; 空字符串无法作为稳定事件来源或可读进度."""
    value = chunk.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_int(chunk: Mapping[str, object], field_name: str) -> int:
    """completed/total 只接受真正的 int; bool 是 int 子类, 不能当计数."""
    value = chunk.get(field_name)
    if type(value) is not int:
        raise ValueError(f"{field_name} must be an integer")
    return value


def project_custom_chunk(chunk: Mapping[str, object], sequence: int) -> StreamEvent:
    """Project one ``stream_mode="custom"`` progress item."""

    # custom 流没有 messages 那种 metadata; type 是唯一的语义标签.
    if chunk.get("type") != "progress":
        raise ValueError("custom chunk type must be progress")

    node = _require_non_empty_str(chunk, "node")
    message = _require_non_empty_str(chunk, "message")
    completed = _require_int(chunk, "completed")
    total = _require_int(chunk, "total")

    # 先拒绝 total<=0, 再检查 completed 区间, 避免 total=0 被误报成 completed.
    if total <= 0:
        raise ValueError("total must be greater than 0")
    if not 0 <= completed <= total:
        raise ValueError("completed must satisfy 0 <= completed <= total")

    return StreamEvent(
        sequence=sequence,
        kind="progress",
        node=node,
        payload={
            "message": message,
            "completed": completed,
            "total": total,
        },
    )
