"""Async application-level orchestration for one persistent conversation turn."""

from typing import cast

from pi_agent.domain.state import AgentState, create_initial_state
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.builder import AsyncAgentGraph
from pi_agent.sessions.config import session_config
from pi_agent.sessions.metadata import SessionCatalog
from pi_agent.sessions.runtime import SessionNotReadyError


async def run_async_session_turn(
    graph: AsyncAgentGraph,
    *,
    session_id: str,
    content: str,
    message_id: str,
    context: AsyncRunContext,
    catalog: SessionCatalog | None = None,
) -> AgentState:
    """Run one async turn against the latest durable state for a session."""
    # session ID 只映射到 thread_id, 不在这里改写 saver 或拼接历史.
    config = session_config(session_id)
    snapshot = await graph.aget_state(config)
    # 暂停 checkpoint 不能用普通新一轮或 Command(resume=...) 绕过.
    if snapshot.next:
        raise SessionNotReadyError(
            f"Session {session_id} is paused and cannot accept a normal user turn."
        )

    result = cast(
        AgentState,
        await graph.ainvoke(
            create_initial_state(content, message_id=message_id),
            config,
            context=context,
            durability="sync",
        ),
    )
    if catalog is not None:
        catalog.record_session(session_id)
    return result
