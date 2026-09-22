"""Application-level orchestration for one persistent conversation turn."""

from typing import cast

from pi_agent.domain.state import AgentState, create_initial_state
from pi_agent.graph.builder import AgentGraph
from pi_agent.graph.context import RunContext
from pi_agent.sessions.config import session_config
from pi_agent.sessions.metadata import SessionCatalog


class SessionNotReadyError(RuntimeError):
    """Raised when a thread is paused and cannot accept a normal user turn."""


def run_session_turn(
    graph: AgentGraph,
    *,
    session_id: str,
    content: str,
    message_id: str,
    context: RunContext,
    catalog: SessionCatalog | None = None,
) -> AgentState:
    """Run a new user turn against the latest durable state for one session."""
    # 会话身份只映射到 thread_id, 不在这里改写或另开 saver.
    config = session_config(session_id)
    snapshot = graph.get_state(config)
    # next 非空表示图停在待执行节点; 普通新一轮不能越过, 也不用 Command(resume=...).
    if snapshot.next:
        raise SessionNotReadyError(
            f"Session {session_id} is paused and cannot accept a normal user turn."
        )

    # 只提交本轮输入, 由 add_messages 合并 checkpoint 历史; 模型/工具留在 context.
    result = cast(
        AgentState,
        graph.invoke(
            create_initial_state(content, message_id=message_id),
            config,
            context=context,
            durability="sync",
        ),
    )
    if catalog is not None:
        catalog.record_session(session_id)
    return result
