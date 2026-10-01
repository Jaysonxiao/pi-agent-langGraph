"""Explicit browser-facing contracts. Never expose raw graph state."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TOOL_NAMES = ("read", "list", "search")
CODING_TOOL_NAMES = ("write", "edit", "propose_command")
ALL_TOOL_NAMES = TOOL_NAMES + CODING_TOOL_NAMES
DEFAULT_TOOL_CALL_LIMITS = {name: 4 for name in TOOL_NAMES}
MAX_TOOL_CALLS_PER_TOOL = 20
ToolName = Literal["read", "list", "search", "write", "edit", "propose_command"]
ToolCallLimits = dict[
    Literal["read", "list", "search"], Annotated[int, Field(ge=0, le=MAX_TOOL_CALLS_PER_TOOL)]
]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewRun(InputModel):
    text: str = Field(min_length=1, max_length=32768)
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class CheckpointAction(InputModel):
    checkpoint_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class CheckpointItem(BaseModel):
    checkpoint_id: str
    created_at: str
    preview: str


class ApprovalAction(InputModel):
    version: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")
    decision: Literal["approve", "reject"]
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class SessionEdit(InputModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class SettingsUpdate(InputModel):
    workspace: str = Field(min_length=1, max_length=4096)
    tools: list[ToolName] = Field(max_length=6)
    tool_limits: ToolCallLimits


class StepDetail(BaseModel):
    event_id: int
    title: str
    node: str
    input: list[dict[str, Any]]
    output: list[dict[str, Any]]
    snapshot_before: dict[str, Any]
    snapshot_after: dict[str, Any]


class SessionItem(BaseModel):
    session_id: str
    title: str
    workspace: str
    archived: bool
    created_at: str
    updated_at: str


RunStatus = Literal[
    "running", "completed", "failed", "cancelled", "needs_recovery", "awaiting_approval"
]


class RunItem(BaseModel):
    run_id: str
    session_id: str
    request_id: str
    status: RunStatus
    created_at: str
    finished_at: str | None = None
    error: str | None = None


class Activity(BaseModel):
    event_id: int
    session_id: str
    run_id: str
    phase: str
    tool_name: str | None = None
    outcome: str | None = None
    created_at: str


class MessageItem(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "tool"]
    text: str
    tool_name: str | None = None
    truncated: bool = False


class MessagePage(BaseModel):
    messages: list[MessageItem]
    checkpoint_id: str | None
    next_before: int | None


class StreamingPreview(BaseModel):
    run_id: str
    message_id: str
    revision: int
    text: str
    status: Literal["streaming", "complete", "discarded"]
    truncated: bool


class SessionView(BaseModel):
    session: SessionItem
    server_epoch: str
    run: RunItem | None
    needs_recovery: bool
    history: MessagePage
    activities: list[Activity]
    preview: StreamingPreview | None = None
    awaiting_approval: bool = False
    proposals: list[dict[str, Any]] = Field(default_factory=list)
