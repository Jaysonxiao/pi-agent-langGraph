"""Projection of LangGraph message-stream chunks into stable events."""

from collections.abc import Mapping

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from pi_agent.events.stream import StreamEvent

# LangChain 类型名/类 -> 稳定对外角色; 不把 ai/human 原样泄漏给 CLI.
_ROLE_BY_TYPE: dict[str, str] = {
    "ai": "assistant",
    "human": "user",
    "system": "system",
    "tool": "tool",
}


def _require_node_name(metadata: Mapping[str, object]) -> str:
    """LangGraph 用 langgraph_node 标明来源; 缺或空字符串都无法填 StreamEvent.node."""
    node = metadata.get("langgraph_node")
    if not isinstance(node, str) or not node:
        raise ValueError("langgraph_node must be a non-empty string in message metadata")
    return node


def _stable_role(message: BaseMessage) -> str:
    """把框架内部角色映射成协议角色, 未知类型直接失败而不是猜."""
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, ToolMessage):
        return "tool"
    role = _ROLE_BY_TYPE.get(getattr(message, "type", ""))
    if role is None:
        raise ValueError(f"unsupported message type {type(message).__name__}")
    return role


def project_message_chunk(
    message: BaseMessage,
    metadata: Mapping[str, object],
    sequence: int,
) -> StreamEvent:
    """Project one ``stream_mode="messages"`` item."""

    payload: dict[str, object] = {
        "role": _stable_role(message),
        "content": message.content,
        "message_id": message.id,
        "is_chunk": isinstance(message, BaseMessageChunk),
    }
    if isinstance(message, AIMessage) and message.usage_metadata is not None:
        payload["usage"] = {
            key: message.usage_metadata.get(key)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
    return StreamEvent(
        sequence=sequence,
        kind="message",
        node=_require_node_name(metadata),
        payload=payload,
    )
