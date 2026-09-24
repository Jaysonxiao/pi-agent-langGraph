"""Runtime-only dependencies for the M8.5 native async graph."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count

from pi_agent.context.runtime import ContextConfig
from pi_agent.extensions.hooks import HookEvent, HookOutcome, HookPhase, HookRegistry
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
    # hook 关联信息只活在运行依赖里, 不进 AgentState / checkpoint.
    hooks: HookRegistry | None = None
    thread_id: str | None = None
    run_id: str | None = None
    # 与 Provider 边界共用同一个 count(), 保证 run/model 事件 sequence 严格递增.
    hook_sequence: Iterator[int] = field(default_factory=count)

    def __post_init__(self) -> None:
        if self.max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be zero or greater.")
        if self.request_timeout_seconds is not None and self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive.")

    async def dispatch_hook(
        self,
        phase: HookPhase,
        *,
        node: str | None = None,
        outcome: HookOutcome | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """派发一个观察型生命周期事件; 未注入 registry 或关联 ID 时静默跳过."""
        if self.hooks is None or self.thread_id is None or self.run_id is None:
            return
        # 只传关联字段. 不要把 tool args / 输出 / 异常正文塞进 HookEvent.
        await self.hooks.dispatch(
            HookEvent(
                phase=phase,
                thread_id=self.thread_id,
                run_id=self.run_id,
                sequence=next(self.hook_sequence),
                node=node,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                outcome=outcome,
            )
        )
