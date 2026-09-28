"""Client connector authenticates before exposing the byte connection."""

import asyncio
from contextlib import suppress

import pytest

from pi_agent.client.transport import connect_tcp
from pi_agent.protocol.transport import LOOPBACK_HOST, TransportError


def test_client_reads_token_from_environment_and_sends_prelude_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        observed: list[bytes] = []

        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            header = await reader.readexactly(4)
            length = int.from_bytes(header, byteorder="big")
            observed.append(header + await reader.readexactly(length))
            writer.write(b"ok")
            await writer.drain()
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()

        server = await asyncio.start_server(peer, LOOPBACK_HOST, 0)
        monkeypatch.setenv("PI_AGENT_REMOTE_TOKEN", "secret")
        connection = await connect_tcp(server.sockets[0].getsockname()[1])
        try:
            assert await connection.read(2) == b"ok"
            assert observed == [b"\x00\x00\x00\x06secret"]
        finally:
            await connection.close()
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_client_requires_token_and_only_connects_to_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.delenv("PI_AGENT_REMOTE_TOKEN", raising=False)
        with pytest.raises(TransportError):
            await connect_tcp(12345)
        with pytest.raises(ValueError):
            await connect_tcp(12345, token="secret", host="0.0.0.0")

    asyncio.run(scenario())
