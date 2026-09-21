"""Serializable state contracts for human approval of file mutations."""

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict

ApprovalStatus = Literal["pending", "approved", "rejected"]


class PendingFileChange(TypedDict):
    """A prepared change retained in checkpoint state until approval."""

    operation: Literal["write", "edit"]
    path: str
    before_sha256: str | None
    after_sha256: str
    after_text: str
    preview: str


class FileApprovalState(TypedDict):
    """State for the isolated approval subgraph."""

    pending_change: PendingFileChange
    approval_status: ApprovalStatus
    rejection_reason: str | None


class FileApprovalStateUpdate(TypedDict, total=False):
    """Partial state update returned by the approval node."""

    approval_status: ApprovalStatus
    rejection_reason: str | None


class ApprovalDecision(BaseModel):
    """Validated value supplied when an interrupted graph is resumed."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str | None = None


def create_file_approval_state(change: PendingFileChange) -> FileApprovalState:
    """Create the initial pending state for one prepared file change."""

    return {
        "pending_change": change,
        "approval_status": "pending",
        "rejection_reason": None,
    }
