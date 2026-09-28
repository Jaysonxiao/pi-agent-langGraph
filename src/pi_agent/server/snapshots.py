"""Allowlisted projection from LangGraph checkpoint state to protocol DTOs."""

from collections.abc import Mapping
from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import StateSnapshot

from pi_agent.protocol.messages import (
    MAX_DISPLAY_TEXT_BYTES,
    MAX_SNAPSHOT_MESSAGES,
    DisplayMessage,
    SessionSnapshot,
)

MAX_SNAPSHOT_TEXT_BYTES = 128 * 1024


def _display_content(message: BaseMessage) -> str | None:
    """Return plain text only; structured blocks and metadata stay private."""
    if not isinstance(message.content, str):
        return None
    encoded = message.content.encode("utf-8", errors="replace")
    return encoded[:MAX_DISPLAY_TEXT_BYTES].decode("utf-8", errors="ignore")


def _display_message(message: object, index: int) -> DisplayMessage | None:
    if not isinstance(message, (HumanMessage, AIMessage, ToolMessage)):
        return None
    text = _display_content(message)
    if text is None:
        return None
    role = (
        "user"
        if isinstance(message, HumanMessage)
        else ("tool" if isinstance(message, ToolMessage) else "assistant")
    )
    message_id = message.id if isinstance(message.id, str) and message.id else f"message-{index}"
    tool_call_id = message.tool_call_id if isinstance(message, ToolMessage) else None
    return DisplayMessage(
        message_id=message_id,
        role=cast(Literal["user", "assistant", "tool"], role),
        text=text,
        tool_call_id=tool_call_id,
    )


def _state_values(snapshot: StateSnapshot) -> Mapping[str, object]:
    return snapshot.values if isinstance(snapshot.values, Mapping) else {}


def _checkpoint_id(snapshot: StateSnapshot) -> str | None:
    config = snapshot.config
    if not isinstance(config, Mapping):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return None
    value = configurable.get("checkpoint_id")
    return value if isinstance(value, str) and value else None


def project_session_snapshot(
    snapshot: StateSnapshot,
    *,
    session_id: str,
    server_epoch: str,
    revision: int,
    run_phase: str = "idle",
    run_outcome: str | None = None,
    active_run_id: str | None = None,
) -> SessionSnapshot:
    """将 checkpoint 与服务端运行状态投影为有界、白名单化的 wire DTO。"""
    values = _state_values(snapshot)
    raw_messages = values.get("messages")
    messages = raw_messages if isinstance(raw_messages, (list, tuple)) else ()
    message_count = len(messages)

    # LangGraph 留有待执行节点表示检查点中断; 只有失败状态映射为公开 error。
    if snapshot.next:
        graph_status: Literal["idle", "running", "interrupted", "error"] = "interrupted"
    elif values.get("status") == "failed":
        graph_status = "error"
    elif values.get("status") in {"ready", "awaiting_tools"}:
        graph_status = "running"
    else:
        graph_status = "idle"

    selected: list[DisplayMessage] = []
    used_text_bytes = 0
    truncated = False

    # 从最新消息倒序挑选, 保证预算紧张时较新的内容优先进入快照。
    for index in range(message_count - 1, -1, -1):
        source = messages[index]
        display = _display_message(source, index)
        if display is None:
            # system、非文本内容和未知消息类型均不出网, 并显式标记展示不完整。
            truncated = True
            continue

        original_content = source.content
        if isinstance(original_content, str) and len(
            original_content.encode("utf-8", errors="replace")
        ) > len(display.text.encode("utf-8")):
            truncated = True

        if len(selected) >= MAX_SNAPSHOT_MESSAGES:
            truncated = True
            break

        remaining_bytes = MAX_SNAPSHOT_TEXT_BYTES - used_text_bytes
        display_bytes = display.text.encode("utf-8")
        if remaining_bytes == 0 and display_bytes:
            truncated = True
            break
        if len(display_bytes) > remaining_bytes:
            # 按 UTF-8 字节边界截断, 避免切开多字节字符; 额度耗尽后不再加入旧消息。
            bounded_text = display_bytes[:remaining_bytes].decode("utf-8", errors="ignore")
            display = DisplayMessage(
                message_id=display.message_id,
                role=display.role,
                text=bounded_text,
                tool_call_id=display.tool_call_id,
            )
            selected.append(display)
            truncated = True
            break

        selected.append(display)
        used_text_bytes += len(display_bytes)

    # 输出维持会话原有时间顺序; 计数仍是 checkpoint 中的全部消息数。
    selected.reverse()
    return SessionSnapshot(
        session_id=session_id,
        server_epoch=server_epoch,
        revision=revision,
        checkpoint_id=_checkpoint_id(snapshot),
        graph_status=graph_status,
        run_phase=cast(Literal["idle", "running", "cancelling", "needs_recovery"], run_phase),
        run_outcome=cast(Literal["completed", "failed", "cancelled"] | None, run_outcome),
        active_run_id=active_run_id,
        message_count=message_count,
        messages=tuple(selected),
        truncated=truncated,
    )
