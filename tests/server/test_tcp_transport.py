"""Loopback listener, serialized writes, deadlines, and shutdown behavior."""

import asyncio
from contextlib import suppress
from typing import cast

import pytest

from pi_agent.protocol.transport import (
    LOOPBACK_HOST,
    AsyncByteConnection,
    AsyncioByteConnection,
    TransportError,
    encode_auth_prelude,
)
from pi_agent.server.transports.tcp import TcpByteServer


def test_listener_refuses_non_loopback_and_invalid_port() -> None:
    async def handler(connection: AsyncByteConnection) -> None:
        await connection.close()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await TcpByteServer.start(handler, token="secret", host="0.0.0.0")
        with pytest.raises(ValueError):
            await TcpByteServer.start(handler, token="secret", host="localhost")
        with pytest.raises(ValueError):
            await TcpByteServer.start(handler, token="secret", port=65536)

    asyncio.run(scenario())


def test_listener_requires_server_token_before_binding() -> None:
    async def handler(connection: AsyncByteConnection) -> None:
        await connection.close()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await TcpByteServer.start(handler, token="")

    asyncio.run(scenario())


def test_authenticated_accept_preserves_coalesced_hello_and_business_bytes() -> None:
    async def scenario() -> None:
        accepted = asyncio.Event()
        observed: list[bytes] = []
        suffix = b'{"type":"hello","version":1}\x00next-payload'

        async def handler(connection: AsyncByteConnection) -> None:
            data = bytearray()
            while len(data) < len(suffix):
                data.extend(await connection.read(len(suffix) - len(data)))
            observed.append(bytes(data))
            accepted.set()

        server = await TcpByteServer.start(handler, token="secret")
        _reader, writer = await asyncio.open_connection(LOOPBACK_HOST, server.port)
        try:
            writer.write(encode_auth_prelude("secret") + suffix)
            await writer.drain()
            await asyncio.wait_for(accepted.wait(), timeout=1)
            assert observed == [suffix]
        finally:
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()
            await server.close()
            await server.close()

    asyncio.run(scenario())


def test_bad_credentials_never_call_authenticated_handler() -> None:
    async def scenario() -> None:
        called = 0

        async def handler(connection: AsyncByteConnection) -> None:
            nonlocal called
            called += 1
            await connection.close()

        server = await TcpByteServer.start(handler, token="secret")
        reader, writer = await asyncio.open_connection(LOOPBACK_HOST, server.port)
        try:
            writer.write(encode_auth_prelude("wrong"))
            await writer.drain()
            assert await asyncio.wait_for(reader.read(1), timeout=1) == b""
            assert called == 0
        finally:
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()
            await server.close()

    asyncio.run(scenario())


def test_server_shutdown_reports_a_handler_that_outlives_its_deadline() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()

        async def handler(_connection: AsyncByteConnection) -> None:
            started.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    continue
            finished.set()

        server = await TcpByteServer.start(
            handler,
            token="secret",
            close_timeout_seconds=0.01,
        )
        _reader, writer = await asyncio.open_connection(LOOPBACK_HOST, server.port)
        try:
            writer.write(encode_auth_prelude("secret"))
            await writer.drain()
            await asyncio.wait_for(started.wait(), timeout=1)

            with pytest.raises(TimeoutError, match="shutdown deadline"):
                await server.close()
            assert not finished.is_set()
        finally:
            release.set()
            await asyncio.wait_for(finished.wait(), timeout=1)
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()

    asyncio.run(scenario())


def test_asyncio_connection_serializes_concurrent_writes() -> None:
    async def scenario() -> None:
        size = 256 * 1024
        received = asyncio.Future[bytes]()

        async def on_peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                received.set_result(await reader.readexactly(size * 2))
            finally:
                writer.close()
                with suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        server = await asyncio.start_server(on_peer, LOOPBACK_HOST, 0)
        reader, writer = await asyncio.open_connection(
            LOOPBACK_HOST, server.sockets[0].getsockname()[1]
        )
        connection = AsyncioByteConnection(reader, writer)
        first = b"A" * size
        second = b"B" * size
        try:
            await asyncio.gather(connection.send(first), connection.send(second))
            actual = await asyncio.wait_for(received, timeout=1)
            assert actual in (first + second, second + first)
        finally:
            await connection.close()
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())


def test_slow_writer_hits_send_deadline_and_aborts_connection() -> None:
    class StalledTransport:
        def __init__(self) -> None:
            self.aborted = False

        def abort(self) -> None:
            self.aborted = True

    class StalledWriter:
        def __init__(self) -> None:
            self.transport = StalledTransport()

        def write(self, data: bytes) -> None:
            del data

        async def drain(self) -> None:
            await asyncio.Event().wait()

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def scenario() -> None:
        writer = StalledWriter()
        connection = AsyncioByteConnection(
            asyncio.StreamReader(),
            cast(asyncio.StreamWriter, writer),
            send_timeout_seconds=0.01,
        )

        with pytest.raises(TransportError, match="deadline"):
            await connection.send(b"slow-peer")
        assert writer.transport.aborted
        assert await connection.read(1) == b""
        await connection.close()
        await connection.close()

    asyncio.run(scenario())


def test_send_budget_and_invalid_read_size_fail_without_queue_growth() -> None:
    async def scenario() -> None:
        async def peer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read()
            writer.close()
            with suppress(ConnectionError, OSError):
                await writer.wait_closed()

        server = await asyncio.start_server(peer, LOOPBACK_HOST, 0)
        reader, writer = await asyncio.open_connection(
            LOOPBACK_HOST, server.sockets[0].getsockname()[1]
        )
        connection = AsyncioByteConnection(reader, writer, max_pending_write_bytes=16)
        try:
            with pytest.raises(ValueError):
                await connection.read(0)
            with pytest.raises(TransportError, match="budget"):
                await connection.send(b"x" * 17)
        finally:
            await connection.close()
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
