"""Loopback-only asyncio TCP listener with an authentication-first gate."""

import asyncio
import math
from collections.abc import Awaitable, Callable

from pi_agent.protocol.transport import (
    LOOPBACK_HOST,
    MAX_PENDING_WRITE_BYTES,
    AsyncByteConnection,
    AsyncioByteConnection,
)
from pi_agent.server.auth import (
    DEFAULT_AUTH_TIMEOUT_SECONDS,
    authenticate_connection,
    load_remote_token,
)

AuthenticatedHandler = Callable[[AsyncByteConnection], Awaitable[None]]
MAX_CONNECTIONS = 16


class TcpByteServer:
    """Own a loopback listener and every accepted connection task."""

    def __init__(
        self,
        *,
        handler: AuthenticatedHandler,
        expected_token: bytes,
        auth_timeout_seconds: float,
        send_timeout_seconds: float,
        close_timeout_seconds: float,
        max_pending_write_bytes: int,
        max_connections: int,
    ) -> None:
        self._handler = handler
        self._expected_token = expected_token
        self._auth_timeout_seconds = auth_timeout_seconds
        self._send_timeout_seconds = send_timeout_seconds
        self._close_timeout_seconds = close_timeout_seconds
        self._max_pending_write_bytes = max_pending_write_bytes
        self._max_connections = max_connections
        self._server: asyncio.Server | None = None
        self._connections: set[AsyncioByteConnection] = set()
        self._handler_tasks: set[asyncio.Task[None]] = set()
        self._closing = False
        self._close_task: asyncio.Task[None] | None = None

    @classmethod
    async def start(
        cls,
        handler: AuthenticatedHandler,
        *,
        token: str | None = None,
        host: str = LOOPBACK_HOST,
        port: int = 0,
        auth_timeout_seconds: float = DEFAULT_AUTH_TIMEOUT_SECONDS,
        send_timeout_seconds: float = 5.0,
        close_timeout_seconds: float = 2.0,
        max_pending_write_bytes: int = MAX_PENDING_WRITE_BYTES,
        max_connections: int = MAX_CONNECTIONS,
    ) -> "TcpByteServer":
        """Start a local listener after checking all fail-closed bounds."""
        _validate_listener_options(host, port, max_connections)
        _validate_timeout(auth_timeout_seconds, "auth_timeout_seconds")
        _validate_timeout(send_timeout_seconds, "send_timeout_seconds")
        _validate_timeout(close_timeout_seconds, "close_timeout_seconds")
        if (
            isinstance(max_pending_write_bytes, bool)
            or not isinstance(max_pending_write_bytes, int)
            or not 1 <= max_pending_write_bytes <= MAX_PENDING_WRITE_BYTES
        ):
            raise ValueError("max_pending_write_bytes is outside the allowed range.")

        result = cls(
            handler=handler,
            expected_token=load_remote_token(token),
            auth_timeout_seconds=auth_timeout_seconds,
            send_timeout_seconds=send_timeout_seconds,
            close_timeout_seconds=close_timeout_seconds,
            max_pending_write_bytes=max_pending_write_bytes,
            max_connections=max_connections,
        )
        result._server = await asyncio.start_server(
            result._accept,
            host=host,
            port=port,
            limit=4 * 1024 + 1,
        )
        return result

    @property
    def port(self) -> int:
        """Return the OS-assigned listening port."""
        if self._server is None or not self._server.sockets:
            raise RuntimeError("TCP server is not listening.")
        return int(self._server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        """Stop accepting, close streams, and join handler tasks once."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_impl())
        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._server is not None:
            self._server.close()

        connection_results = await asyncio.gather(
            *(connection.close() for connection in tuple(self._connections)),
            return_exceptions=True,
        )
        connection_close_failed = any(
            isinstance(result, BaseException) for result in connection_results
        )
        current_task = asyncio.current_task()
        tasks = [task for task in self._handler_tasks if task is not current_task]
        for task in tasks:
            task.cancel()
        pending: set[asyncio.Task[None]] = set()
        if tasks:
            _done, pending = await asyncio.wait(tasks, timeout=self._close_timeout_seconds)
            for task in pending:
                task.cancel()

        listener_close_failed = False
        if self._server is not None:
            try:
                async with asyncio.timeout(self._close_timeout_seconds):
                    await self._server.wait_closed()
            except TimeoutError:
                listener_close_failed = True

        if pending or listener_close_failed:
            raise TimeoutError("TCP server shutdown deadline exceeded.")
        if connection_close_failed:
            raise RuntimeError("TCP connection shutdown failed.")

    def _accept(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if self._closing or len(self._connections) >= self._max_connections:
            writer.close()
            return

        connection = AsyncioByteConnection(
            reader,
            writer,
            send_timeout_seconds=self._send_timeout_seconds,
            close_timeout_seconds=self._close_timeout_seconds,
            max_pending_write_bytes=self._max_pending_write_bytes,
        )
        self._connections.add(connection)
        task = asyncio.create_task(self._handle_connection(reader, connection))
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        connection: AsyncioByteConnection,
    ) -> None:
        try:
            authenticated = await authenticate_connection(
                reader,
                self._expected_token,
                timeout_seconds=self._auth_timeout_seconds,
            )
            if authenticated and not self._closing:
                await self._handler(connection)
        except (ConnectionError, OSError):
            # Peer errors fail closed and never include credentials in logs or responses.
            pass
        except Exception:
            # An accept callback failure must not escape into the asyncio server callback.
            pass
        finally:
            await connection.close()
            self._connections.discard(connection)


def _validate_listener_options(host: str, port: int, max_connections: int) -> None:
    if host != LOOPBACK_HOST:
        raise ValueError(f"TCP listener must bind to {LOOPBACK_HOST}.")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer between 0 and 65535.")
    if (
        isinstance(max_connections, bool)
        or not isinstance(max_connections, int)
        or not 1 <= max_connections <= MAX_CONNECTIONS
    ):
        raise ValueError(f"max_connections must be between 1 and {MAX_CONNECTIONS}.")


def _validate_timeout(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive number.")
