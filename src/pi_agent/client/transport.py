"""Loopback client connector that authenticates before returning a stream."""

import asyncio
import math
import os

from pi_agent.protocol.transport import (
    LOOPBACK_HOST,
    AsyncByteConnection,
    AsyncioByteConnection,
    TransportError,
    encode_auth_prelude,
)

REMOTE_TOKEN_ENV = "PI_AGENT_REMOTE_TOKEN"


async def connect_tcp(
    port: int,
    *,
    host: str = LOOPBACK_HOST,
    token: str | None = None,
    connect_timeout_seconds: float = 5.0,
    send_timeout_seconds: float = 5.0,
    close_timeout_seconds: float = 2.0,
) -> AsyncByteConnection:
    """Connect to loopback, send the auth prelude, then return the byte port."""
    if host != LOOPBACK_HOST:
        raise ValueError(f"TCP client must connect to {LOOPBACK_HOST}.")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535.")
    _validate_timeout(connect_timeout_seconds, "connect_timeout_seconds")
    _validate_timeout(send_timeout_seconds, "send_timeout_seconds")
    _validate_timeout(close_timeout_seconds, "close_timeout_seconds")

    candidate = os.environ.get(REMOTE_TOKEN_ENV) if token is None else token
    if candidate is None:
        raise TransportError("Remote authentication token is required.")
    try:
        prelude = encode_auth_prelude(candidate)
    except ValueError:
        raise TransportError("Remote authentication token is invalid.") from None

    try:
        async with asyncio.timeout(connect_timeout_seconds):
            reader, writer = await asyncio.open_connection(host=host, port=port)
    except TimeoutError as error:
        raise TransportError("Remote connection deadline exceeded.") from error
    except (ConnectionError, OSError) as error:
        raise TransportError("Remote connection failed.") from error

    connection = AsyncioByteConnection(
        reader,
        writer,
        send_timeout_seconds=send_timeout_seconds,
        close_timeout_seconds=close_timeout_seconds,
    )
    try:
        await connection.send(prelude)
    except TransportError:
        await connection.close()
        raise
    return connection


def _validate_timeout(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive number.")
