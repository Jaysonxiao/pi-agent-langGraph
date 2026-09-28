"""Wire DTO contracts stay strict and independent of graph state."""

import pytest
from pydantic import TypeAdapter, ValidationError

from pi_agent.protocol.messages import (
    CLIENT_MESSAGE_ADAPTER,
    MAX_REQUEST_ID,
    ClientHello,
    ClientRequest,
    DisplayMessage,
    ProtocolError,
    ServerEvent,
    ServerResponse,
)


def test_client_hello_accepts_an_unknown_integer_version_for_handshake() -> None:
    message = CLIENT_MESSAGE_ADAPTER.validate_python({"type": "hello", "version": 999})

    assert isinstance(message, ClientHello)
    assert message.version == 999


def test_client_hello_preserves_large_unknown_integer_for_handshake() -> None:
    message = CLIENT_MESSAGE_ADAPTER.validate_python({"type": "hello", "version": 2**128})

    assert isinstance(message, ClientHello)
    assert message.version == 2**128


@pytest.mark.parametrize("version", ["1", True, 1.0, -1])
def test_client_hello_rejects_coercion_and_negative_versions(version: object) -> None:
    with pytest.raises(ValidationError):
        CLIENT_MESSAGE_ADAPTER.validate_python({"type": "hello", "version": version})


@pytest.mark.parametrize("request_id", [True, 0, -1, MAX_REQUEST_ID + 1, "1"])
def test_request_id_must_be_a_strict_positive_bounded_integer(request_id: object) -> None:
    with pytest.raises(ValidationError):
        CLIENT_MESSAGE_ADAPTER.validate_python(
            {
                "type": "request",
                "request_id": request_id,
                "request": {"command": "create_session"},
            }
        )


def test_create_session_has_no_client_selected_configuration() -> None:
    message = CLIENT_MESSAGE_ADAPTER.validate_python(
        {
            "type": "request",
            "request_id": 1,
            "request": {"command": "create_session"},
        }
    )

    assert isinstance(message, ClientRequest)
    assert message.request.command == "create_session"


@pytest.mark.parametrize(
    "command_payload",
    [
        {"command": "create_session", "workspace": "C:/outside"},
        {"command": "get_snapshot"},
        {"command": "prompt", "session_id": "s1", "text": ""},
        {"command": "unknown", "session_id": "s1"},
    ],
)
def test_commands_reject_missing_extra_or_unknown_fields(
    command_payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CLIENT_MESSAGE_ADAPTER.validate_python(
            {"type": "request", "request_id": 1, "request": command_payload}
        )


def test_dto_rejects_server_direction_message() -> None:
    with pytest.raises(ValidationError):
        CLIENT_MESSAGE_ADAPTER.validate_python(
            {"type": "response", "request_id": 1, "command": "prompt", "ok": True}
        )


def test_protocol_dtos_are_immutable() -> None:
    hello = ClientHello(type="hello", version=1)

    with pytest.raises(ValidationError):
        hello.version = 2


def test_server_event_union_uses_event_discriminator() -> None:
    adapter: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)
    event = adapter.validate_python(
        {
            "type": "event",
            "event": "run_started",
            "request_id": 1,
            "session_id": "s1",
            "run_id": "r1",
        }
    )

    assert event.event == "run_started"


def test_display_message_limit_counts_utf8_bytes() -> None:
    valid_text = "中" * (8192 // 3)
    valid = DisplayMessage(message_id="m1", role="assistant", text=valid_text)
    assert len(valid.text.encode("utf-8")) <= 8192

    with pytest.raises(ValidationError):
        DisplayMessage(message_id="m1", role="assistant", text="中" * (8192 // 3 + 1))


@pytest.mark.parametrize(
    "ok,error",
    [
        (
            True,
            ProtocolError(code="internal_error", message="failed"),
        ),
        (False, None),
    ],
)
def test_response_success_and_error_fields_must_agree(
    ok: bool, error: ProtocolError | None
) -> None:
    with pytest.raises(ValidationError):
        ServerResponse(
            type="response",
            request_id=1,
            command="prompt",
            ok=ok,
            error=error,
        )
