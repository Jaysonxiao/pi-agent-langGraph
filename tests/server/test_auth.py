"""Authentication prelude boundaries and the learner-owned auth gate."""

import asyncio

import pytest

from pi_agent.protocol.transport import (
    AUTH_HEADER_BYTES,
    MAX_AUTH_TOKEN_BYTES,
    decode_auth_length,
    encode_auth_prelude,
)
from pi_agent.server.auth import (
    AuthenticationConfigurationError,
    authenticate_connection,
    load_remote_token,
)


def test_auth_token_is_required_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PI_AGENT_REMOTE_TOKEN", raising=False)

    with pytest.raises(AuthenticationConfigurationError):
        load_remote_token()
    with pytest.raises(AuthenticationConfigurationError):
        load_remote_token("")
    with pytest.raises(AuthenticationConfigurationError):
        load_remote_token("x" * (MAX_AUTH_TOKEN_BYTES + 1))
    assert load_remote_token("secret") == b"secret"


def test_auth_prelude_uses_a_bounded_big_endian_length() -> None:
    encoded = encode_auth_prelude("token-✓")
    byte_length = len("token-✓".encode())

    assert len(encoded[:AUTH_HEADER_BYTES]) == AUTH_HEADER_BYTES
    assert decode_auth_length(encoded[:AUTH_HEADER_BYTES]) == byte_length
    assert encoded[AUTH_HEADER_BYTES:] == "token-✓".encode()

    with pytest.raises(ValueError):
        encode_auth_prelude("x" * (MAX_AUTH_TOKEN_BYTES + 1))


def test_authentication_preserves_bytes_coalesced_after_the_prelude() -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        suffix = b'{"type":"hello","version":1}\x00business-frame'
        reader.feed_data(encode_auth_prelude("secret") + suffix)
        reader.feed_eof()

        assert await authenticate_connection(reader, b"secret")
        assert await reader.readexactly(len(suffix)) == suffix

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "presented",
    [
        encode_auth_prelude("wrong"),
        (MAX_AUTH_TOKEN_BYTES + 1).to_bytes(AUTH_HEADER_BYTES, byteorder="big"),
        b"\x00\x00",
    ],
)
def test_invalid_auth_prelude_is_rejected(presented: bytes) -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(presented)
        reader.feed_eof()

        assert not await authenticate_connection(reader, b"secret")

    asyncio.run(scenario())


def test_authentication_timeout_fails_closed() -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()

        assert not await authenticate_connection(reader, b"secret", timeout_seconds=0.01)

    asyncio.run(scenario())
