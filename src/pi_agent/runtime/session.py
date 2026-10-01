"""Shared async session runner used by application boundaries."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from langgraph.types import Command

from pi_agent.context.instructions import INSTRUCTION_FILENAME
from pi_agent.context.runtime import ContextConfig
from pi_agent.domain.state import AgentState
from pi_agent.extensions import HookRegistry
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.builder import build_async_tool_graph
from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.streaming import TextObserver
from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.coding import CodingExecutor, coding_definitions
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.runtime.read_only import create_async_read_only_registry
from pi_agent.security import WorkspacePathPolicy
from pi_agent.sessions import open_async_sqlite_checkpointer, run_async_session_turn
from pi_agent.sessions.config import session_config
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
    enabled_tools: tuple[str, ...] = field(default=("read", "list", "search"), kw_only=True)
    tool_call_limits: Mapping[str, int] = field(default_factory=dict, kw_only=True)
    instruction_filename: str = field(default=INSTRUCTION_FILENAME, kw_only=True)
    prompt_template: str = field(default="{instructions}", kw_only=True)
    text_observer: TextObserver | None = field(default=None, kw_only=True)
    coding_executor: CodingExecutor | None = field(default=None, kw_only=True)


async def run_session(
    config: SessionRuntimeConfig,
    *,
    model: AsyncChatModel,
    content: str,
    message_id: str,
    resume: bool = False,
) -> AgentState:
    """Run a prompt with injected dependencies and durable async checkpoints."""
    tools, definitions = create_async_read_only_registry(
        config.workspace, enabled_tools=config.enabled_tools
    )
    executor = config.coding_executor
    if executor is not None:
        definitions += coding_definitions(executor.files, executor.executables)
    binder = getattr(model, "bind_tools", None)
    if callable(binder) and (
        not isinstance(model, CompatibleAsyncChatModel) or model.supports_tool_binding
    ):
        from pi_agent.models.tool_binding import tool_schema

        model = binder([tool_schema(tool) for tool in definitions])
    context = AsyncRunContext(
        model=model,
        tools=tools,
        max_tool_rounds=max(1, sum(config.tool_call_limits.values()))
        if config.tool_call_limits
        else 4,
        tool_call_limits=config.tool_call_limits,
        retry_policy=config.retry_policy,
        request_timeout_seconds=config.request_timeout_seconds,
        text_observer=config.text_observer,
        coding_executor=executor,
        context_config=ContextConfig(
            workspace_policy=WorkspacePathPolicy(config.workspace),
            active_path=".",
            instruction_filename=config.instruction_filename,
            prompt_template=config.prompt_template,
        ),
        hooks=config.hooks,
        thread_id=config.session_id,
        run_id=config.run_id,
        cancellation_token=config.cancellation_token,
    )
    async with open_async_sqlite_checkpointer(config.database) as saver:
        if resume:
            graph = build_async_tool_graph(saver)
            snapshot = await graph.aget_state(session_config(config.session_id))
            if not snapshot.next and not snapshot.interrupts:
                raise ValueError("No pending session checkpoint to resume.")
            state = cast(
                AgentState,
                await graph.ainvoke(
                    Command(
                        resume={item.id: item.value["proposal_id"] for item in snapshot.interrupts}
                    )
                    if snapshot.interrupts and executor is not None
                    else None,
                    session_config(config.session_id),
                    context=context,
                    durability="sync",
                ),
            )
            SqliteSessionCatalog(config.database).record_session(config.session_id)
            return state
        state = await run_async_session_turn(
            build_async_tool_graph(saver),
            session_id=config.session_id,
            content=content,
            message_id=message_id,
            context=context,
            catalog=SqliteSessionCatalog(config.database),
        )
    return state
