"""Tool lookup and model-protocol result normalization."""

import json
from collections.abc import Iterable
from typing import Literal

from langchain_core.messages import ToolCall, ToolMessage

from pi_agent.tools.base import ExecutableTool, ToolArgumentError

ToolFailureCode = Literal[
    "unknown_tool",
    "invalid_arguments",
    "tool_execution_error",
    "tool_round_limit",
]


class ToolRegistry:
    """Immutable-by-interface lookup table for runtime tool capabilities."""

    def __init__(self, tools: Iterable[ExecutableTool] = ()) -> None:
        registered: dict[str, ExecutableTool] = {}
        for tool in tools:
            if tool.name in registered:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            registered[tool.name] = tool
        self._tools = registered

    def find(self, name: str) -> ExecutableTool | None:
        """Return a registered tool without exposing the mutable lookup table."""
        return self._tools.get(name)

    @property
    def tools(self) -> tuple[ExecutableTool, ...]:
        """Return a stable read-only view in registration order."""
        return tuple(self._tools.values())

    def execute_call(self, tool_call: ToolCall) -> ToolMessage:
        """Validate and execute one model-requested tool call.

        Outcomes: success, unknown tool, invalid arguments, and handler exception.
        Every outcome preserves the source call ID and name.
        """
        tool = self.find(tool_call["name"])
        if tool is None:
            return create_error_tool_message(
                tool_call,
                code="unknown_tool",
                message=f"Unknown tool: {tool_call['name']}",
            )

        try:
            content = tool.invoke(tool_call["args"])
        except ToolArgumentError as exc:
            return create_error_tool_message(
                tool_call,
                code="invalid_arguments",
                message=str(exc),
                details=exc.details,
            )
        except Exception as exc:
            return create_error_tool_message(
                tool_call,
                code="tool_execution_error",
                message=str(exc),
            )

        call_id = _require_call_id(tool_call)
        return ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=tool_call["name"],
            status="success",
            id=_tool_result_message_id(call_id),
        )


def create_error_tool_message(
    tool_call: ToolCall,
    *,
    code: ToolFailureCode,
    message: str,
    details: object | None = None,
) -> ToolMessage:
    """Build a deterministic model-visible error with call correlation intact."""
    payload: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    call_id = _require_call_id(tool_call)
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        tool_call_id=call_id,
        name=tool_call["name"],
        status="error",
        id=_tool_result_message_id(call_id),
    )


def _require_call_id(tool_call: ToolCall) -> str:
    """Reject malformed provider output before constructing a ToolMessage."""
    call_id = tool_call.get("id")
    if not call_id:
        raise ValueError("Tool call id must be non-empty.")
    return call_id


def _tool_result_message_id(call_id: str) -> str:
    """Keep message identity deterministic without reusing the call-ID namespace."""
    return f"tool-result:{call_id}"
