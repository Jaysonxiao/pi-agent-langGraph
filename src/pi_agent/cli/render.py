"""Pure text rendering for stable runtime events."""

import json
from collections.abc import Iterable, Iterator, Mapping

from pi_agent.closing import close_iterator
from pi_agent.events.stream import StreamEvent


def _compact_json(value: object) -> str:
    """稳定紧凑 JSON, 与 JSONL 同一套 separators; 给非字符串 content 和通用 payload 用."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _non_empty_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def render_event(event: StreamEvent) -> str:
    """Render one event as a human-readable line without writing to stdout."""

    payload = event.payload

    if event.kind == "progress":
        # 进度条只展示可读文案和计数, 不把整个 payload 摊开.
        return (
            f"[progress] {event.node}: {payload.get('message')} "
            f"({payload.get('completed')}/{payload.get('total')})"
        )

    if event.kind == "message":
        content = payload.get("content")
        # 多模态 content 可能是 list/dict, 用 JSON 而不是 str() 伪装.
        if not isinstance(content, str):
            content = _compact_json(content)
        return f"[message] {event.node}/{payload.get('role')}: {content}"

    if event.kind == "error":
        # 先给人看 message/code; 真实投影把详情放在 payload.error 里.
        nested = payload.get("error")
        nested_payload: Mapping[str, object] = nested if isinstance(nested, dict) else {}
        detail = (
            _non_empty_str(payload, "message")
            or _non_empty_str(payload, "code")
            or _non_empty_str(nested_payload, "message")
            or _non_empty_str(nested_payload, "code")
        )
        if detail is None:
            detail = _compact_json(payload)
        return f"[error] {event.node}: {detail}"

    # state_update/tool 等保留完整 payload, 调用方不能丢 status/error 字段.
    return f"[{event.kind}] {event.node}: {_compact_json(payload)}"


def iter_text(events: Iterable[StreamEvent]) -> Iterator[str]:
    """Render events lazily while preserving their order."""

    iterator = iter(events)
    try:
        for event in iterator:
            yield render_event(event)
    finally:
        close_iterator(iterator)
