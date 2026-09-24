"""Safe completion boundary for fragmented streamed tool calls."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from langchain_core.messages import AIMessage, AIMessageChunk


def assemble_tool_call_message(
    chunks: Iterable[AIMessageChunk],
    /,
) -> AIMessage:
    """Build one executable assistant message only after every argument is valid."""
    # 只合并调用方已经切出来的 fragment, 不自己去缓冲整条 provider 流.
    merged: dict[int, dict[str, str]] = {}
    saw_fragment = False
    for chunk in chunks:
        for fragment in chunk.tool_call_chunks or ():
            saw_fragment = True
            index, name, call_id, args_text = _parse_fragment(fragment)
            slot = merged.setdefault(index, {"name": "", "id": "", "args": ""})
            # 后续分片通常只带 args; 同一 index 上冲突的 name/id 视为畸形 fragment.
            _assign_stable_field(slot, "name", name)
            _assign_stable_field(slot, "id", call_id)
            slot["args"] += args_text

    if not saw_fragment:
        raise ValueError("tool call stream is empty")

    tool_calls: list[dict[str, object]] = []
    for index in sorted(merged):
        slot = merged[index]
        if not slot["name"].strip():
            raise ValueError("tool call name is required")
        if not slot["id"].strip():
            raise ValueError("tool call id is required")
        tool_calls.append(
            {
                "name": slot["name"],
                "args": _parse_object_args(slot["args"]),
                "id": slot["id"],
                "type": "tool_call",
            }
        )
    return AIMessage(content="", tool_calls=tool_calls)


def _parse_fragment(fragment: object) -> tuple[int, str, str, str]:
    """Read one provider fragment; never put raw args into the error text."""
    if not isinstance(fragment, Mapping):
        raise ValueError("tool call fragment is malformed")
    index = fragment.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        raise ValueError("tool call fragment is malformed")
    name = _optional_text(fragment.get("name"))
    call_id = _optional_text(fragment.get("id"))
    args = fragment.get("args")
    if args is None:
        args_text = ""
    elif isinstance(args, str):
        args_text = args
    else:
        raise ValueError("tool call fragment is malformed")
    return index, name, call_id, args_text


def _assign_stable_field(slot: dict[str, str], key: str, value: str) -> None:
    """Keep the first nonblank name/id; reject a different value for the same index."""
    if not value:
        return
    current = slot[key]
    if current and current != value:
        raise ValueError("tool call fragment is malformed")
    if not current:
        slot[key] = value


def _optional_text(value: object) -> str:
    """Accept missing/blank name or id on intermediate fragments."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("tool call fragment is malformed")
    return value


def _parse_object_args(text: str) -> dict[str, object]:
    """Decode completed args JSON; incomplete or non-object values are rejected."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # 错误里不得带上半截 JSON, 以免泄露路径或密钥.
        raise ValueError("tool call arguments are incomplete") from None
    if not isinstance(parsed, dict):
        raise ValueError("tool call arguments are incomplete")
    return parsed
