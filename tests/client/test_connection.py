"""Client hello negotiation, single-reader dispatch, and protocol shutdown."""

import asyncio

import pytest

from pi_agent.client.connection import ClientConnection
from pi_agent.client.errors import ClientProtocolError, UnsupportedProtocolVersionError
from pi_agent.protocol import (
    FrameDecoder,
    encode_client_message,
    encode_frame,
    encode_server_message,
)
from pi_agent.protocol.messages import (
    PROTOCOL_VERSION,
    ClientHello,
    ProtocolError,
    ServerHello,
    ServerHelloError,
    ServerMessage,
)


class MemoryByteConnection:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.sent: list[bytes] = []
        self.closed = False
        self.sent_event = asyncio.Event()

    async def read(self, max_bytes: int) -> bytes:
        del max_bytes
        return await self.incoming.get()

    async def send(self, data: bytes) -> None:
        self.sent.append(data)
        self.sent_event.set()

    async def close(self) -> None:
        self.closed = True
        self.incoming.put_nowait(b"")

    def feed(self, data: bytes) -> None:
        self.incoming.put_nowait(data)

    async def wait_for_sent(self, count: int) -> None:
        while len(self.sent) < count:
            self.sent_event.clear()
            await asyncio.wait_for(self.sent_event.wait(), timeout=1)


def _server_frame(message: ServerMessage) -> bytes:
    return encode_frame(encode_server_message(message))


def test_connection_sends_hello_and_accepts_server_epoch_once() -> None:
    async def scenario() -> None:
        transport = MemoryByteConnection()
        messages: list[object] = []
        hellos: list[str] = []
        disconnected: list[Exception] = []
        connection = ClientConnection(
            transport,
            on_message=messages.append,
            on_hello=lambda hello: hellos.append(hello.server_epoch),
            on_disconnect=disconnected.append,
        )
        task = asyncio.create_task(connection.start())
        await transport.wait_for_sent(1)
        transport.feed(_server_frame(ServerHello(type="hello", version=1, server_epoch="epoch-1")))
        hello = await task

        decoder = FrameDecoder()
        payloads = [payload for chunk in transport.sent for payload in decoder.feed(chunk)]
        assert len(payloads) == 1
        assert payloads[0] == encode_client_message(
            ClientHello(type="hello", version=PROTOCOL_VERSION)
        )
        assert hello.server_epoch == "epoch-1"
        assert hellos == ["epoch-1"]
        assert connection.connected
        assert messages == []
        await connection.close()
        assert transport.closed
        assert len(disconnected) == 1

    asyncio.run(scenario())


def test_connection_rejects_server_version_error() -> None:
    async def scenario() -> None:
        transport = MemoryByteConnection()
        connection = ClientConnection(
            transport,
            on_message=lambda _message: None,
            on_hello=lambda _hello: None,
            on_disconnect=lambda _error: None,
        )
        task = asyncio.create_task(connection.start())
        await transport.wait_for_sent(1)
        transport.feed(
            _server_frame(
                ServerHelloError(
                    type="hello_error",
                    error=ProtocolError(
                        code="unsupported_version", message="Protocol version is not supported."
                    ),
                )
            )
        )

        with pytest.raises(UnsupportedProtocolVersionError):
            await task
        assert transport.closed

    asyncio.run(scenario())


def test_wrong_direction_message_after_handshake_fails_connection() -> None:
    async def scenario() -> None:
        transport = MemoryByteConnection()
        closed = asyncio.Event()
        errors: list[Exception] = []
        connection = ClientConnection(
            transport,
            on_message=lambda _message: None,
            on_hello=lambda _hello: None,
            on_disconnect=lambda error: _record_disconnect(errors, closed, error),
        )
        task = asyncio.create_task(connection.start())
        await transport.wait_for_sent(1)
        transport.feed(_server_frame(ServerHello(type="hello", version=1, server_epoch="epoch-1")))
        await task
        transport.feed(encode_frame(b'{"type":"hello","version":1}'))
        await asyncio.wait_for(closed.wait(), timeout=1)

        assert transport.closed
        assert len(errors) == 1
        assert isinstance(errors[0], ClientProtocolError)

    asyncio.run(scenario())


def _record_disconnect(errors: list[Exception], closed: asyncio.Event, error: Exception) -> None:
    errors.append(error)
    closed.set()
