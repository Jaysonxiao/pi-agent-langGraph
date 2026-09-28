"""Strict, versioned wire DTOs for the remote protocol.

These models describe only the public protocol. They intentionally do not reuse
LangGraph state, provider objects, or persisted session records.
"""

from typing import Annotated, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

PROTOCOL_VERSION = 1
MAX_IDENTIFIER_LENGTH = 128
MAX_REQUEST_ID = (1 << 63) - 1
MAX_DISPLAY_TEXT_BYTES = 8 * 1024
MAX_SNAPSHOT_MESSAGES = 20

Identifier: TypeAlias = Annotated[str, Field(min_length=1, max_length=MAX_IDENTIFIER_LENGTH)]
RequestId: TypeAlias = Annotated[int, Field(strict=True, ge=1, le=MAX_REQUEST_ID)]
ProtocolVersion: TypeAlias = Annotated[int, Field(strict=True, ge=0)]


def _require_bounded_utf8_text(value: str) -> str:
    try:
        if len(value.encode("utf-8", errors="strict")) > MAX_DISPLAY_TEXT_BYTES:
            raise ValueError("Display text exceeds its byte limit.")
    except UnicodeEncodeError as error:
        raise ValueError("Display text must be valid Unicode.") from error
    return value


DisplayText: TypeAlias = Annotated[
    str,
    Field(max_length=MAX_DISPLAY_TEXT_BYTES),
    AfterValidator(_require_bounded_utf8_text),
]


class ProtocolModel(BaseModel):
    """Base configuration shared by all wire DTOs."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ClientHello(ProtocolModel):
    type: Literal["hello"]
    version: ProtocolVersion


class CreateSession(ProtocolModel):
    command: Literal["create_session"]


class GetSnapshot(ProtocolModel):
    command: Literal["get_snapshot"]
    session_id: Identifier


class Prompt(ProtocolModel):
    command: Literal["prompt"]
    session_id: Identifier
    text: Annotated[str, Field(min_length=1, max_length=64 * 1024)]


class Cancel(ProtocolModel):
    command: Literal["cancel"]
    session_id: Identifier
    run_id: Identifier


ClientCommand: TypeAlias = Annotated[
    CreateSession | GetSnapshot | Prompt | Cancel,
    Field(discriminator="command"),
]


class ClientRequest(ProtocolModel):
    type: Literal["request"]
    request_id: RequestId
    request: ClientCommand


ClientMessage: TypeAlias = Annotated[
    ClientHello | ClientRequest,
    Field(discriminator="type"),
]


class DisplayMessage(ProtocolModel):
    message_id: Identifier
    role: Literal["user", "assistant", "tool"]
    text: DisplayText
    tool_call_id: Identifier | None = None


class SessionSnapshot(ProtocolModel):
    session_id: Identifier
    server_epoch: Identifier
    revision: Annotated[int, Field(strict=True, ge=0, le=MAX_REQUEST_ID)]
    checkpoint_id: Identifier | None
    graph_status: Literal["idle", "running", "interrupted", "error"]
    run_phase: Literal["idle", "running", "cancelling", "needs_recovery"]
    run_outcome: Literal["completed", "failed", "cancelled"] | None
    active_run_id: Identifier | None
    message_count: Annotated[int, Field(strict=True, ge=0, le=MAX_REQUEST_ID)]
    messages: Annotated[tuple[DisplayMessage, ...], Field(max_length=MAX_SNAPSHOT_MESSAGES)]
    truncated: bool

    @field_validator("messages", mode="before")
    @classmethod
    def _json_array_to_tuple(cls, value: object) -> object:
        """Normalize JSON arrays to the immutable internal snapshot sequence."""
        return tuple(value) if isinstance(value, list) else value


class ServerHello(ProtocolModel):
    type: Literal["hello"]
    version: Literal[1]
    server_epoch: Identifier


class ProtocolError(ProtocolModel):
    code: Literal[
        "unsupported_version",
        "invalid_request",
        "unauthorized",
        "not_found",
        "busy",
        "needs_recovery",
        "internal_error",
    ]
    message: Annotated[str, Field(min_length=1, max_length=256)]


class ServerHelloError(ProtocolModel):
    type: Literal["hello_error"]
    error: ProtocolError


class ServerResponse(ProtocolModel):
    type: Literal["response"]
    request_id: RequestId
    command: Literal["create_session", "get_snapshot", "prompt", "cancel"]
    ok: bool
    snapshot: SessionSnapshot | None = None
    error: ProtocolError | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "ServerResponse":
        if self.ok == (self.error is not None):
            raise ValueError("Response success and error fields are inconsistent.")
        if not self.ok and self.snapshot is not None:
            raise ValueError("Failed responses cannot contain a snapshot.")
        return self


class SnapshotEvent(ProtocolModel):
    type: Literal["event"]
    event: Literal["snapshot"]
    snapshot: SessionSnapshot


class RunStartedEvent(ProtocolModel):
    type: Literal["event"]
    event: Literal["run_started"]
    request_id: RequestId
    session_id: Identifier
    run_id: Identifier


class ProgressEvent(ProtocolModel):
    type: Literal["event"]
    event: Literal["progress"]
    session_id: Identifier
    run_id: Identifier
    phase: Literal["queued", "model", "tool", "persisting"]


class SessionRemovedEvent(ProtocolModel):
    type: Literal["event"]
    event: Literal["session_removed"]
    session_id: Identifier


ServerEvent: TypeAlias = Annotated[
    SnapshotEvent | RunStartedEvent | ProgressEvent | SessionRemovedEvent,
    Field(discriminator="event"),
]

ServerMessage: TypeAlias = ServerHello | ServerHelloError | ServerResponse | ServerEvent

CLIENT_MESSAGE_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
SERVER_MESSAGE_ADAPTER: TypeAdapter[ServerMessage] = TypeAdapter(ServerMessage)
