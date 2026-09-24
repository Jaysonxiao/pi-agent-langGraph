"""Async provider-session assembly used by the M8.8 CLI boundary."""

from collections.abc import AsyncIterator, Mapping
from typing import cast

from langchain_core.messages import BaseMessage

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.read_only import create_cli_async_read_only_registry
from pi_agent.context.runtime import ContextConfig
from pi_agent.domain.state import AgentState, create_initial_state
from pi_agent.events.message import project_message_chunk
from pi_agent.events.stream import StreamEvent, project_stream_update
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.builder import build_async_tool_graph
from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.tool_binding import tool_schema
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.security import WorkspacePathPolicy
from pi_agent.sessions import open_async_sqlite_checkpointer, run_async_session_turn
from pi_agent.sessions.config import session_config
from pi_agent.sessions.metadata import SqliteSessionCatalog
from pi_agent.sessions.runtime import SessionNotReadyError


async def run_provider_session(
    options: ProviderCliOptions,
    *,
    model: AsyncChatModel,
    message_id: str,
    retry_policy: RetryPolicy | None = None,
    request_timeout_seconds: float | None = None,
    allowed_executables: frozenset[str] = frozenset(),
) -> AgentState:
    """Assemble one async graph/session run without creating a provider implicitly."""
    # model 必须由调用方注入; 这里不根据 provider 隐式创建 client.
    tools, definitions = create_cli_async_read_only_registry(
        options.workspace,
        database=options.database,
        session_id=options.session_id,
        allowed_executables=allowed_executables,
    )
    binder = getattr(model, "bind_tools", None)
    if callable(binder) and (
        not isinstance(model, CompatibleAsyncChatModel) or model.supports_tool_binding
    ):
        model = binder([tool_schema(tool) for tool in definitions])
    async with open_async_sqlite_checkpointer(options.database) as saver:
        return await run_async_session_turn(
            build_async_tool_graph(saver),
            session_id=options.session_id,
            content=options.prompt,
            message_id=message_id,
            context=AsyncRunContext(
                model=model,
                tools=tools,
                retry_policy=retry_policy,
                request_timeout_seconds=request_timeout_seconds,
                context_config=ContextConfig(
                    workspace_policy=WorkspacePathPolicy(options.workspace),
                    active_path=".",
                ),
            ),
            catalog=SqliteSessionCatalog(options.database),
        )


async def stream_provider_session(
    options: ProviderCliOptions,
    *,
    model: AsyncChatModel,
    message_id: str,
    retry_policy: RetryPolicy | None = None,
    request_timeout_seconds: float | None = None,
    allowed_executables: frozenset[str] = frozenset(),
) -> AsyncIterator[StreamEvent]:
    """Consume graph updates incrementally while preserving durable session state."""
    tools, definitions = create_cli_async_read_only_registry(
        options.workspace,
        database=options.database,
        session_id=options.session_id,
        allowed_executables=allowed_executables,
    )
    binder = getattr(model, "bind_tools", None)
    if callable(binder) and (
        not isinstance(model, CompatibleAsyncChatModel) or model.supports_tool_binding
    ):
        model = binder([tool_schema(tool) for tool in definitions])
    context = AsyncRunContext(
        model=model,
        tools=tools,
        retry_policy=retry_policy,
        request_timeout_seconds=request_timeout_seconds,
        context_config=ContextConfig(
            workspace_policy=WorkspacePathPolicy(options.workspace), active_path="."
        ),
    )
    async with open_async_sqlite_checkpointer(options.database) as saver:
        graph = build_async_tool_graph(saver)
        config = session_config(options.session_id)
        if (await graph.aget_state(config)).next:
            raise SessionNotReadyError("Paused session cannot accept a normal user turn.")
        chunks = graph.astream(
            create_initial_state(options.prompt, message_id=message_id),
            config,
            context=context,
            stream_mode="updates",
            durability="sync",
        )
        sequence = 0
        try:
            async for chunk in chunks:
                if not isinstance(chunk, Mapping):
                    raise ValueError("Unexpected graph update shape.")
                for node, raw_update in chunk.items():
                    if not isinstance(node, str) or not isinstance(raw_update, Mapping):
                        raise ValueError("Unexpected graph node update.")
                    update = cast(Mapping[str, object], raw_update)
                    messages = update.get("messages")
                    if isinstance(messages, list):
                        for message in messages:
                            if isinstance(message, BaseMessage):
                                yield project_message_chunk(
                                    message, {"langgraph_node": node}, sequence
                                )
                                sequence += 1
                    yield project_stream_update(node, update, sequence)
                    sequence += 1
        finally:
            aclose = getattr(chunks, "aclose", None)
            if callable(aclose):
                await aclose()
    SqliteSessionCatalog(options.database).record_session(options.session_id)
