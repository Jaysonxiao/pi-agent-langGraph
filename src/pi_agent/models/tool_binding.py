"""Provider-neutral tool schema export and binding boundary for M8.3."""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from pi_agent.models.base import ChatModel
from pi_agent.tools.base import ExecutableTool

ToolSchema = dict[str, object]


class ToolBindingError(ValueError):
    """Safe, provider-independent failures while binding model tools."""


@runtime_checkable
class BindableChatModel(ChatModel, Protocol):
    """Chat model capability required when at least one tool is registered."""

    def bind_tools(self, tools: Sequence[Mapping[str, object]], /) -> ChatModel:
        """Return a model configured with the supplied provider-neutral schemas."""
        ...


def tool_schema(tool: ExecutableTool) -> ToolSchema:
    """Export one registry tool as the standard function-tool envelope."""
    parameters = dict(tool.args_schema.model_json_schema())
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        },
    }


def bind_registered_tools(
    model: ChatModel,
    tools: Sequence[ExecutableTool],
    /,
) -> ChatModel:
    """Bind registry schemas to a capable model, preserving order and safe errors.

    The zero-tool path intentionally returns the original model without requiring
    provider tool-binding support.  The non-empty path is the learner-owned core
    of M8.3: export schemas, call ``bind_tools`` once, and normalize provider
    failures to ``ToolBindingError`` without exposing SDK messages or secrets.
    """
    if not tools:
        return model

    if not isinstance(model, BindableChatModel):
        raise ToolBindingError("model_does_not_support_tool_binding")

    schemas = [tool_schema(tool) for tool in tools]
    try:
        return model.bind_tools(schemas)
    except Exception as exc:
        raise ToolBindingError(f"tool_binding_failed:{type(exc).__name__}") from None
