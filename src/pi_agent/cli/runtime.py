"""Async provider-session assembly used by the M8.8 CLI boundary."""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from itertools import count
from typing import cast
from uuid import uuid4

from langchain_core.messages import BaseMessage
from langgraph.errors import NodeCancelledError

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.read_only import create_cli_async_read_only_registry
from pi_agent.context.runtime import ContextConfig
from pi_agent.domain.state import AgentState, create_initial_state
from pi_agent.events.message import project_message_chunk
from pi_agent.events.stream import StreamEvent, project_stream_update
from pi_agent.extensions import HookEvent, HookOutcome, HookPhase, HookRegistry
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

# 取消是控制信号, 不是普通失败. GeneratorExit 来自消费者 aclose;
# NodeCancelledError 是 LangGraph 在图边界对节点内 CancelledError 的包装.
_CANCELLATION_SIGNALS: tuple[type[BaseException], ...] = (
    asyncio.CancelledError,
    GeneratorExit,
    NodeCancelledError,
)


async def _dispatch_run_hook(
    hooks: HookRegistry | None,
    *,
    phase: HookPhase,
    thread_id: str,
    run_id: str,
    sequence: int,
    outcome: HookOutcome | None = None,
) -> None:
    """派发一个 run 级观察事件; 未注入 registry 时不做任何事."""
    if hooks is None:
        return
    # 观察型 hook 失败是 fail-open 的: dispatch 已把普通异常收敛成脱敏的
    # HookFailure, 这里不让它影响 Agent 主流程, 也不把它投影成 StreamEvent.
    await hooks.dispatch(
        HookEvent(
            phase=phase,
            thread_id=thread_id,
            run_id=run_id,
            sequence=sequence,
            outcome=outcome,
        )
    )


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
    hooks: HookRegistry | None = None,
) -> AsyncGenerator[StreamEvent, None]:
    """Consume graph updates incrementally while preserving durable session state."""
    # 返回类型用 AsyncGenerator 而非 AsyncIterator: 消费者可以 aclose() 提前结束本轮 run.
    # run_id 只用于关联本次调用的观察事件; 它不进入 AgentState, 也不进 checkpoint.
    run_id = uuid4().hex
    hook_sequence = count()
    # run_start 必须早于第一个 StreamEvent, 否则消费者在首个事件后 aclose 就拿不到配对.
    await _dispatch_run_hook(
        hooks,
        phase="run_start",
        thread_id=options.session_id,
        run_id=run_id,
        sequence=next(hook_sequence),
    )
    outcome: HookOutcome = "failed"
    try:
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
            # 把同一份 run 关联信息和 sequence 交给节点, 不写进 checkpoint.
            hooks=hooks,
            thread_id=options.session_id,
            run_id=run_id,
            hook_sequence=hook_sequence,
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
            # 图内失败被节点收敛成 status=failed 的 update, 不会抛异常; 因此 run_end
            # 的 outcome 取最后一次看到的图状态, 而不是"没有异常就算成功".
            last_status: object = None
            try:
                async for chunk in chunks:
                    if not isinstance(chunk, Mapping):
                        raise ValueError("Unexpected graph update shape.")
                    for node, raw_update in chunk.items():
                        if not isinstance(node, str) or not isinstance(raw_update, Mapping):
                            raise ValueError("Unexpected graph node update.")
                        update = cast(Mapping[str, object], raw_update)
                        if "status" in update:
                            last_status = update["status"]
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
        outcome = "completed" if last_status == "completed" else "failed"
    except BaseException as exc:
        # 只给 run_end 分类, 原异常照常向上传播; 消费者 aclose 的 GeneratorExit 同理.
        outcome = "cancelled" if isinstance(exc, _CANCELLATION_SIGNALS) else "failed"
        raise
    finally:
        # 无论正常结束、失败还是取消, run_start 都恰好配对一个 run_end.
        await _dispatch_run_hook(
            hooks,
            phase="run_end",
            thread_id=options.session_id,
            run_id=run_id,
            sequence=next(hook_sequence),
            outcome=outcome,
        )
