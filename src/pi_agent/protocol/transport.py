"""Byte-oriented connection contract and asyncio stream adapter."""

import asyncio
import math
from contextlib import suppress
from typing import Protocol

from pi_agent.protocol.errors import FrameError

AUTH_HEADER_BYTES = 4
MAX_AUTH_TOKEN_BYTES = 4 * 1024
MAX_PENDING_WRITE_BYTES = 2 * 1024 * 1024
LOOPBACK_HOST = "127.0.0.1"


class TransportError(ConnectionError):
    """A bounded transport operation failed or exceeded its deadline."""


class AsyncByteConnection(Protocol):
    """An authorized ordered byte stream; callers own one read loop."""

    async def read(self, max_bytes: int) -> bytes:
        """Read up to ``max_bytes`` from the byte stream."""
        ...

    async def send(self, data: bytes) -> None:
        """Send bytes atomically with respect to other send calls."""
        ...

    async def close(self) -> None:
        """Close and join the underlying stream within its configured bound."""
        ...


class AsyncioByteConnection:
    """Serialize writes and bound buffered bytes and stream cleanup."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        send_timeout_seconds: float = 5.0,
        close_timeout_seconds: float = 2.0,
        max_pending_write_bytes: int = MAX_PENDING_WRITE_BYTES,
    ) -> None:
        _validate_positive_timeout(send_timeout_seconds, "send_timeout_seconds")
        _validate_positive_timeout(close_timeout_seconds, "close_timeout_seconds")
        if (
            isinstance(max_pending_write_bytes, bool)
            or not isinstance(max_pending_write_bytes, int)
            or max_pending_write_bytes < 1
        ):
            raise ValueError("max_pending_write_bytes must be a positive integer.")
        self._reader = reader
        self._writer = writer
        self._send_timeout_seconds = send_timeout_seconds
        self._close_timeout_seconds = close_timeout_seconds
        self._max_pending_write_bytes = max_pending_write_bytes
        self._pending_write_bytes = 0
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    async def read(self, max_bytes: int) -> bytes:
        """Read a bounded chunk; one caller should own the read loop."""
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer.")
        if self._closed:
            return b""
        try:
            return await self._reader.read(max_bytes)
        except (ConnectionError, OSError) as error:
            raise TransportError("Remote connection read failed.") from error

    async def send(self, data: bytes) -> None:
        """Write one byte string without interleaving concurrent callers."""
        if not isinstance(data, bytes):
            raise TypeError("Transport data must be bytes.")
        if not data:
            return
        if self._closed:
            raise TransportError("Remote connection is closed.")
        if self._pending_write_bytes + len(data) > self._max_pending_write_bytes:
            self._abort()
            raise TransportError("Remote connection output budget exceeded.")

        self._pending_write_bytes += len(data)
        try:
            async with asyncio.timeout(self._send_timeout_seconds):
                async with self._write_lock:
                    if self._closed:
                        raise TransportError("Remote connection is closed.")
                    self._writer.write(data)
                    await self._writer.drain()
        except TimeoutError as error:
            self._abort()
            raise TransportError("Remote connection send deadline exceeded.") from error
        except (ConnectionError, OSError) as error:
            await self.close()
            raise TransportError("Remote connection send failed.") from error
        finally:
            self._pending_write_bytes -= len(data)

    async def close(self) -> None:
        """Idempotently close the writer and bound wait_closed()."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_impl())
        await asyncio.shield(self._close_task)

    async def _close_impl(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._writer.close()
        try:
            async with asyncio.timeout(self._close_timeout_seconds):
                await self._writer.wait_closed()
        except TimeoutError:
            self._writer.transport.abort()
        except (ConnectionError, OSError):
            with suppress(ConnectionError, OSError):
                self._writer.transport.abort()

    def _abort(self) -> None:
        """Drop buffered output immediately after a hard transport failure."""
        if self._closed:
            return
        self._closed = True
        self._writer.transport.abort()


def _validate_positive_timeout(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive number.")


def validate_auth_token(token: str) -> bytes:
    """Encode a configured token without exposing its value in failures."""
    if not isinstance(token, str) or not token:
        raise ValueError("Remote authentication token is required.")
    try:
        token_bytes = token.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("Remote authentication token is invalid.") from error
    if len(token_bytes) > MAX_AUTH_TOKEN_BYTES:
        raise ValueError("Remote authentication token exceeds the configured limit.")
    return token_bytes


def encode_auth_prelude(token: str) -> bytes:
    """Encode the standalone four-byte-length-prefixed authentication token."""
    token_bytes = validate_auth_token(token)
    return len(token_bytes).to_bytes(AUTH_HEADER_BYTES, byteorder="big") + token_bytes


def decode_auth_length(header: bytes) -> int:
    """Validate an authentication frame header before reading its body."""
    if not isinstance(header, bytes) or len(header) != AUTH_HEADER_BYTES:
        raise FrameError("Invalid authentication prelude.")
    length = int.from_bytes(header, byteorder="big", signed=False)
    if not 1 <= length <= MAX_AUTH_TOKEN_BYTES:
        raise FrameError("Invalid authentication prelude.")
    return length
