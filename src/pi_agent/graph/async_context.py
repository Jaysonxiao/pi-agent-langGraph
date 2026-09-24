"""Runtime-only dependencies for the M8.5 native async graph."""

from dataclasses import dataclass, field

from pi_agent.context.runtime import ContextConfig
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.tools.async_registry import AsyncToolRegistry


@dataclass(frozen=True, slots=True)
class AsyncRunContext:
    """Keep the async model and context dependencies out of checkpoint state."""

    model: AsyncChatModel
    context_config: ContextConfig = field(default_factory=ContextConfig)
    tools: AsyncToolRegistry = field(default_factory=AsyncToolRegistry)
    cancellation_token: AsyncCancellationToken = field(default_factory=AsyncCancellationToken)
    max_tool_rounds: int = 4
    retry_policy: RetryPolicy | None = None
    request_timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be zero or greater.")
        if self.request_timeout_seconds is not None and self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive.")
