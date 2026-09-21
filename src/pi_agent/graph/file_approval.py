"""已准备文件变更的 LangGraph 审批边界.

本节点只负责暂停、校验恢复值并返回状态增量; 不改 proposal、不写文件.
``interrupt()`` 恢复时会从节点开头重跑, 因此中断前不得有不可幂等副作用.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from pi_agent.domain.approval import (
    ApprovalDecision,
    FileApprovalState,
    FileApprovalStateUpdate,
    PendingFileChange,
)

FILE_APPROVAL_NODE = "file_approval"


def build_file_approval_request(change: PendingFileChange) -> dict[str, object]:
    """构造有界、可 JSON 序列化的人审载荷, 不泄漏完整 ``after_text``."""

    return {
        "kind": "file_change_approval",
        "question": "Approve this workspace file change?",
        "change": {
            "operation": change["operation"],
            "path": change["path"],
            "before_sha256": change["before_sha256"],
            "after_sha256": change["after_sha256"],
            "preview": change["preview"],
        },
    }


def file_approval_node(state: FileApprovalState) -> FileApprovalStateUpdate:
    """暂停等待人审, 只返回 ``approval_status`` / ``rejection_reason`` 增量."""

    # 已批准或已拒绝的状态不得再次 interrupt, 避免重复审批.
    if state["approval_status"] != "pending":
        raise ValueError("approval_status must be pending before interrupt")

    # 不要用 try/except 包住 interrupt: GraphInterrupt 属于 Exception, 会被误当成普通失败.
    resume_value = interrupt(build_file_approval_request(state["pending_change"]))
    decision = ApprovalDecision.model_validate(resume_value)
    if decision.decision == "approve":
        return {"approval_status": "approved", "rejection_reason": None}
    return {"approval_status": "rejected", "rejection_reason": decision.reason}


def build_file_approval_graph() -> CompiledStateGraph[
    FileApprovalState, None, FileApprovalState, FileApprovalState
]:
    """编译带 checkpointer 的审批子图, 生产级持久化留到 M6."""

    builder = StateGraph(FileApprovalState)
    builder.add_node(FILE_APPROVAL_NODE, file_approval_node)
    builder.add_edge(START, FILE_APPROVAL_NODE)
    builder.add_edge(FILE_APPROVAL_NODE, END)
    return builder.compile(checkpointer=InMemorySaver())
