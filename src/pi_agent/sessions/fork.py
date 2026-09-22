"""Create an isolated session branch from a completed checkpoint."""

from langgraph.graph import START

from pi_agent.graph.builder import AgentGraph
from pi_agent.sessions.config import checkpoint_config, session_config
from pi_agent.sessions.history import SessionCheckpoint, project_session_checkpoint


class SessionForkError(RuntimeError):
    """Raised when a requested session fork is unsafe or impossible."""


def fork_session(
    graph: AgentGraph,
    *,
    source_session_id: str,
    checkpoint_id: str,
    target_session_id: str,
) -> SessionCheckpoint:
    """Fork completed state into an empty target thread without executing nodes."""
    source_config = checkpoint_config(source_session_id, checkpoint_id)
    target_config = session_config(target_session_id)
    # 分支必须落到另一条 thread, 不能覆盖 source 自己.
    if source_session_id == target_session_id:
        raise SessionForkError(f"Source session {source_session_id} cannot be forked onto itself.")

    # 只看 created_at 判断占用; 不能用空 state mapping 猜测 thread 是否存在.
    target_snapshot = graph.get_state(target_config)
    if target_snapshot.created_at is not None:
        raise SessionForkError(f"Target session {target_session_id} already exists.")

    source_snapshot = graph.get_state(source_config)
    if source_snapshot.created_at is None:
        raise SessionForkError(
            f"Source checkpoint {checkpoint_id} was not found in session {source_session_id}."
        )
    source_summary = project_session_checkpoint(source_snapshot)
    if source_summary.status != "completed":
        raise SessionForkError(
            f"Source checkpoint {checkpoint_id} in session {source_session_id} is not completed."
        )
    # 下一轮 input 边界会留下 next=__start__, 那只是排队的新输入, 不是暂停;
    # 其余待执行节点说明图停在运行中途, status=completed 也不能当分支起点.
    pending_nodes = tuple(node for node in source_summary.next_nodes if node != START)
    if pending_nodes:
        raise SessionForkError(
            f"Source checkpoint {checkpoint_id} in session {source_session_id} "
            f"is paused before {', '.join(pending_nodes)}."
        )

    # 只写入选中状态; 不 invoke、不 copy_thread、不重放旧节点.
    updated_config = graph.update_state(target_config, source_snapshot.values, as_node="model")
    return project_session_checkpoint(graph.get_state(updated_config))
