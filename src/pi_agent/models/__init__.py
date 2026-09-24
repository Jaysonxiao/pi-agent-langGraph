"""Model ports, deterministic adapters and M8 configuration."""

from pi_agent.models.adapter import CompatibleChatModel, ProviderClient
from pi_agent.models.async_adapter import (
    AsyncProviderClient,
    AsyncStreamingProviderClient,
    CompatibleAsyncChatModel,
)
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.async_fake import AsyncFakeChatModel
from pi_agent.models.async_stream import collect_async_response
from pi_agent.models.base import ChatModel
from pi_agent.models.config import ModelConfig, ModelConfigError, ModelOptions, resolve_model_config
from pi_agent.models.errors import ModelFactoryError, ModelProviderError
from pi_agent.models.fake import FakeChatModel
from pi_agent.models.tool_binding import (
    BindableChatModel,
    ToolBindingError,
    bind_registered_tools,
    tool_schema,
)
from pi_agent.models.usage import TokenUsage, UsageLedger, normalize_usage

__all__ = [
    "AsyncChatModel",
    "AsyncFakeChatModel",
    "AsyncProviderClient",
    "AsyncStreamingProviderClient",
    "BindableChatModel",
    "ChatModel",
    "CompatibleAsyncChatModel",
    "CompatibleChatModel",
    "FakeChatModel",
    "ModelConfig",
    "ModelConfigError",
    "ModelFactoryError",
    "ModelOptions",
    "ModelProviderError",
    "ProviderClient",
    "TokenUsage",
    "ToolBindingError",
    "UsageLedger",
    "bind_registered_tools",
    "collect_async_response",
    "normalize_usage",
    "resolve_model_config",
    "tool_schema",
]
