"""Shared async session runner used by application boundaries."""

from dataclasses import dataclass, field
from pathlib import Path

from pi_agent.context.runtime import ContextConfig
from pi_agent.domain.state import AgentState
from pi_agent.extensions import HookRegistry
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.builder import build_async_tool_graph
from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.runtime.read_only import create_async_read_only_registry
from pi_agent.security import WorkspacePathPolicy
from pi_agent.sessions import open_async_sqlite_checkpointer, run_async_session_turn
from pi_agent.sessions.metadata import SqliteSessionCatalog


@dataclass(frozen=True, slots=True)
class SessionRuntimeConfig:
    """Server-owned runtime paths and policy; clients cannot provide these values."""

    database: Path
    workspace: Path
    session_id: str
    retry_policy: RetryPolicy | None = None
    request_timeout_seconds: float | None = None
    hooks: HookRegistry | None = None
    run_id: str | None = None
    cancellation_token: AsyncCancellationToken = field(default_factory=AsyncCancellationToken)


async def run_session(
    config: SessionRuntimeConfig,
    *,
    model: AsyncChatModel,
    content: str,
    message_id: str,
) -> AgentState:
    """Run a prompt with injected dependencies and durable async checkpoints."""
    tools, definitions = create_async_read_only_registry(config.workspace)
    binder = getattr(model, "bind_tools", None)
    if callable(binder) and (
        not isinstance(model, CompatibleAsyncChatModel) or model.supports_tool_binding
    ):
        from pi_agent.models.tool_binding import tool_schema

        model = binder([tool_schema(tool) for tool in definitions])
    context = AsyncRunContext(
        model=model,
        tools=tools,
        retry_policy=config.retry_policy,
        request_timeout_seconds=config.request_timeout_seconds,
        context_config=ContextConfig(
            workspace_policy=WorkspacePathPolicy(config.workspace), active_path="."
        ),
        hooks=config.hooks,
        thread_id=config.session_id,
        run_id=config.run_id,
        cancellation_token=config.cancellation_token,
    )
    async with open_async_sqlite_checkpointer(config.database) as saver:
        state = await run_async_session_turn(
            build_async_tool_graph(saver),
            session_id=config.session_id,
            content=content,
            message_id=message_id,
            context=context,
            catalog=SqliteSessionCatalog(config.database),
        )
    return state
