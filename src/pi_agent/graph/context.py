"""Per-run dependencies that must not be persisted in graph state."""

from dataclasses import dataclass, field

from pi_agent.context.runtime import ContextConfig
from pi_agent.models.base import ChatModel
from pi_agent.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class RunContext:
    """Runtime dependencies injected when invoking the graph."""

    model: ChatModel
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    max_tool_rounds: int = 4
    context_config: ContextConfig = field(default_factory=ContextConfig)

    def __post_init__(self) -> None:
        """Reject invalid loop configuration before graph execution starts."""
        if self.max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be zero or greater.")
