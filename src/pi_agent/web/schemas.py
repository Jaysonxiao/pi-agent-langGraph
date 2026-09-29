"""Explicit browser-facing contracts. Never expose raw graph state."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TOOL_NAMES = ("read", "list", "search")
DEFAULT_TOOL_CALL_LIMITS = {name: 4 for name in TOOL_NAMES}
MAX_TOOL_CALLS_PER_TOOL = 20
ToolName = Literal["read", "list", "search"]
ToolCallLimits = dict[ToolName, Annotated[int, Field(ge=0, le=MAX_TOOL_CALLS_PER_TOOL)]]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewRun(InputModel):
    text: str = Field(min_length=1, max_length=32768)
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class SessionEdit(InputModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class SettingsUpdate(InputModel):
    workspace: str = Field(min_length=1, max_length=4096)
    tools: list[ToolName] = Field(max_length=3)
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


RunStatus = Literal["running", "completed", "failed", "cancelled", "needs_recovery"]


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


class SessionView(BaseModel):
    session: SessionItem
    server_epoch: str
    run: RunItem | None
    needs_recovery: bool
    history: MessagePage
    activities: list[Activity]
