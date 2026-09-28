"""Protocol codec rejects unsafe JSON and preserves public DTO boundaries."""

import json

import pytest

from pi_agent.protocol.codec import (
    decode_client_message,
    decode_server_message,
    encode_client_message,
    encode_server_message,
)
from pi_agent.protocol.errors import ProtocolValidationError
from pi_agent.protocol.messages import (
    ClientHello,
    DisplayMessage,
    ServerHello,
    ServerResponse,
    SessionSnapshot,
)


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"{",
        b"[]",
        b'{"type":"hello","version":1,"version":1}',
        b'{"type":"hello","version":NaN}',
        b'{"type":"hello","version":Infinity}',
        b'{"type":"hello","version":-Infinity}',
        b'{"type":"hello","version":"1"}',
        b'{"type":"request","request_id":1,"request":{"command":"create_session","token":"secret-marker"}}',
    ],
)
def test_client_decoder_rejects_invalid_or_untrusted_payloads(payload: bytes) -> None:
    with pytest.raises(ProtocolValidationError) as error:
        decode_client_message(payload)

    assert str(error.value) == "Invalid protocol message."
    assert "secret-marker" not in str(error.value)


def test_client_decoder_preserves_unknown_integer_version_for_handshake() -> None:
    message = decode_client_message(b'{"type":"hello","version":900}')

    assert isinstance(message, ClientHello)
    assert message.version == 900


def test_client_decoder_enforces_payload_size_limit() -> None:
    with pytest.raises(ProtocolValidationError):
        decode_client_message(b'{"type":"hello","version":1}', max_payload_bytes=8)


def test_server_decoder_accepts_server_message() -> None:
    message = decode_server_message(b'{"type":"hello","version":1,"server_epoch":"boot-1"}')

    assert isinstance(message, ServerHello)
    assert message.server_epoch == "boot-1"


def test_snapshot_response_round_trips_json_message_array_to_immutable_tuple() -> None:
    snapshot = SessionSnapshot(
        session_id="session-1",
        server_epoch="epoch-1",
        revision=3,
        checkpoint_id=None,
        graph_status="idle",
        run_phase="idle",
        run_outcome="completed",
        active_run_id=None,
        message_count=1,
        messages=(DisplayMessage(message_id="message-1", role="assistant", text="done"),),
        truncated=False,
    )
    response = ServerResponse(
        type="response",
        request_id=1,
        command="get_snapshot",
        ok=True,
        snapshot=snapshot,
    )

    decoded = decode_server_message(encode_server_message(response))

    assert decoded == response
    assert isinstance(decoded, ServerResponse)
    assert decoded.snapshot is not None
    assert isinstance(decoded.snapshot.messages, tuple)


def test_server_decoder_rejects_client_direction_message() -> None:
    with pytest.raises(ProtocolValidationError):
        decode_server_message(b'{"type":"hello","version":1}')


def test_client_encoder_is_compact_utf8_and_does_not_add_frame_header() -> None:
    payload = encode_client_message(ClientHello(type="hello", version=1))

    assert payload == b'{"type":"hello","version":1}'
    assert json.loads(payload) == {"type": "hello", "version": 1}


def test_server_encoder_validates_direction_and_payload_limit() -> None:
    message = ServerHello(type="hello", version=1, server_epoch="boot-1")

    with pytest.raises(ProtocolValidationError):
        encode_server_message(message, max_payload_bytes=8)
    with pytest.raises(ProtocolValidationError):
        encode_server_message(
            {"type": "hello", "version": 1},  # type: ignore[arg-type]
        )


def test_codec_errors_do_not_echo_invalid_payload() -> None:
    payload = b'{"type":"hello","version":1,"secret":"do-not-return"}'

    with pytest.raises(ProtocolValidationError) as error:
        decode_client_message(payload)

    assert "do-not-return" not in str(error.value)
