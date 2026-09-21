"""Stable, JSON-serializable projection of LangGraph update chunks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StreamEventKind = Literal["state_update", "tool", "error", "message", "progress"]

# 工具相关节点; 或增量里带 tool_rounds 时, 归类为 tool 事件.
_TOOL_NODES = frozenset({"tools", "tool_limit"})


class StreamEvent(BaseModel):
    """Version-one event envelope for state/update streaming."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    kind: StreamEventKind
    node: str
    payload: dict[str, object]


def _is_json_serializable(value: object) -> bool:
    """Accept only values that json.dumps can emit without a custom default."""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False
    return True


def _json_payload(update: Mapping[str, object]) -> dict[str, object]:
    """Copy JSON-safe fields; drop LangChain messages and other framework objects."""
    payload: dict[str, object] = {}
    for key, value in update.items():
        # 不可序列化就整键丢弃, 不用 str(value) 伪装成文本.
        if _is_json_serializable(value):
            payload[key] = value
    return payload


def _classify_update(node_name: str, update: Mapping[str, object]) -> StreamEventKind:
    """Classify error and tool before the generic state-update fallback."""
    # error=None 是成功路径的显式字段, 只有非空才算错误事件.
    if update.get("error") is not None:
        return "error"
    if node_name in _TOOL_NODES or "tool_rounds" in update:
        return "tool"
    return "state_update"


def project_stream_update(
    node_name: str, update: Mapping[str, object], sequence: int
) -> StreamEvent:
    """Project one LangGraph ``stream_mode="updates"`` chunk.

    LangGraph 已经按节点交出一整份状态增量;
    本函数只做翻译: 标上语义 kind, 滤掉不能进 JSON 的字段, 原样带上 sequence/node.
    """

    return StreamEvent(
        sequence=sequence,
        kind=_classify_update(node_name, update),
        node=node_name,
        payload=_json_payload(update),
    )
