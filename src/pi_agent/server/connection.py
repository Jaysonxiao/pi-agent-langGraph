"""Protocol handshake and request lifetime for an authenticated byte stream."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Literal, Protocol

from pi_agent.protocol import (
    DEFAULT_MAX_FRAME_BYTES,
    FrameDecoder,
    FrameError,
    ProtocolValidationError,
    decode_client_message,
    encode_frame,
    encode_server_message,
)
from pi_agent.protocol.messages import (
    PROTOCOL_VERSION,
    ClientHello,
    ClientMessage,
    ClientRequest,
    ProtocolError,
    RunStartedEvent,
    ServerEvent,
    ServerHello,
    ServerHelloError,
    ServerMessage,
    ServerResponse,
)

MAX_IN_FLIGHT_REQUESTS = 8
READ_CHUNK_BYTES = 64 * 1024
ConnectionPhase = Literal["awaiting_hello", "ready", "closing", "closed"]
EventSender = Callable[[ServerEvent], Awaitable[None]]


class ByteConnection(Protocol):
    """The already-authenticated, ordered byte transport."""

    async def read(self, max_bytes: int) -> bytes: ...

    async def send(self, data: bytes) -> None: ...

    async def close(self) -> None: ...


class MessageDispatcher(Protocol):
    """Application command boundary used after protocol admission."""

    async def dispatch_message(
        self,
        request: ClientRequest,
        *,
        send_event: EventSender,
    ) -> ServerResponse: ...

    async def cancel_owned_run(self, session_id: str, run_id: str, /) -> None: ...


class ServerConnection:
    """Own one hello state machine, one reader, and bounded request tasks."""

    def __init__(
        self,
        connection: ByteConnection,
        dispatcher: MessageDispatcher,
        *,
        server_epoch: str,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        max_in_flight: int = MAX_IN_FLIGHT_REQUESTS,
    ) -> None:
        if not server_epoch or server_epoch != server_epoch.strip():
            raise ValueError("server_epoch must be a non-empty identifier.")
        if isinstance(max_in_flight, bool) or not isinstance(max_in_flight, int):
            raise ValueError("max_in_flight must be an integer.")
        if not 1 <= max_in_flight <= MAX_IN_FLIGHT_REQUESTS:
            raise ValueError(f"max_in_flight must be between 1 and {MAX_IN_FLIGHT_REQUESTS}.")
        self._connection = connection
        self._dispatcher = dispatcher
        self._server_epoch = server_epoch
        self._max_frame_bytes = max_frame_bytes
        self._max_in_flight = max_in_flight
        self._phase: ConnectionPhase = "awaiting_hello"
        self._last_request_id = 0
        self._request_tasks: set[asyncio.Task[None]] = set()
        self._owned_runs: dict[int, tuple[str, str]] = {}

    @property
    def phase(self) -> ConnectionPhase:
        return self._phase

    async def serve(self) -> None:
        """Read framed DTOs until EOF/failure, then cancel and join owned work."""
        decoder = FrameDecoder(max_frame_bytes=self._max_frame_bytes)
        try:
            while self._phase not in {"closing", "closed"}:
                chunk = await self._connection.read(READ_CHUNK_BYTES)
                if not chunk:
                    decoder.finish()
                    break
                for payload in decoder.feed(chunk):
                    message = decode_client_message(
                        payload,
                        max_payload_bytes=self._max_frame_bytes,
                    )
                    await self._accept_message(message)
                    if self._phase in {"closing", "closed"}:
                        break
        except (FrameError, ProtocolValidationError, ConnectionError, OSError):
            # Invalid bytes or peer failure close the stream without reflecting input.
            pass
        finally:
            await self._close_owned_connection()

    async def _accept_message(self, message: ClientMessage) -> None:
        if self._phase == "awaiting_hello":
            if not isinstance(message, ClientHello):
                await self._send_message(
                    _request_error(message, "invalid_request", "Hello is required first.")
                )
                self._phase = "closing"
                return
            if message.version != PROTOCOL_VERSION:
                await self._send_message(
                    ServerHelloError(
                        type="hello_error",
                        error=ProtocolError(
                            code="unsupported_version",
                            message="Protocol version is not supported.",
                        ),
                    )
                )
                self._phase = "closing"
                return
            self._phase = "ready"
            await self._send_message(
                ServerHello(
                    type="hello",
                    version=1,
                    server_epoch=self._server_epoch,
                )
            )
            return

        if self._phase != "ready":
            return
        if isinstance(message, ClientHello):
            await self._send_message(
                ServerHelloError(
                    type="hello_error",
                    error=ProtocolError(
                        code="invalid_request",
                        message="Hello may only be sent once.",
                    ),
                )
            )
            self._phase = "closing"
            return

        if message.request_id <= self._last_request_id:
            # Request IDs are monotonic within this connection; closing avoids an
            # ambiguous second response with an ID that may still be in flight.
            self._phase = "closing"
            return
        self._last_request_id = message.request_id
        if len(self._request_tasks) >= self._max_in_flight:
            await self._send_message(
                _request_error(message, "busy", "Connection request capacity is full.")
            )
            return

        task = asyncio.create_task(self._dispatch(message))
        self._request_tasks.add(task)
        task.add_done_callback(self._request_tasks.discard)

    async def _dispatch(self, request: ClientRequest) -> None:
        async def send_request_event(message: ServerEvent) -> None:
            await self._send_request_event(request, message)

        try:
            response = await self._dispatcher.dispatch_message(
                request,
                send_event=send_request_event,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            response = _request_error(
                request,
                "internal_error",
                "The server could not complete the request.",
            )
        await self._send_message(response)
        self._owned_runs.pop(request.request_id, None)

    async def _send_request_event(self, request: ClientRequest, message: ServerEvent) -> None:
        if self._phase in {"closing", "closed"}:
            # A prompt must not start after shutdown has snapshotted owned runs.
            # Raising cancellation stops ServerCommandService before coordinator.run().
            raise asyncio.CancelledError
        if isinstance(message, RunStartedEvent):
            self._owned_runs[request.request_id] = (message.session_id, message.run_id)
        await self._send_message(message)

    async def _send_message(self, message: ServerMessage) -> None:
        if self._phase in {"closing", "closed"}:
            return
        payload = encode_server_message(message, max_payload_bytes=self._max_frame_bytes)
        await self._connection.send(encode_frame(payload, max_frame_bytes=self._max_frame_bytes))

    async def _close_owned_connection(self) -> None:
        if self._phase == "closed":
            return
        self._phase = "closing"
        # A bounded cancellation failure must not prevent transport teardown.
        for session_id, run_id in tuple(self._owned_runs.values()):
            with suppress(Exception):
                await self._dispatcher.cancel_owned_run(session_id, run_id)
        tasks = tuple(self._request_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._connection.close()
        self._phase = "closed"


def _request_error(
    request: ClientRequest,
    code: Literal["invalid_request", "busy", "internal_error"],
    message: str,
) -> ServerResponse:
    return ServerResponse(
        type="response",
        request_id=request.request_id,
        command=request.request.command,
        ok=False,
        error=ProtocolError(code=code, message=message),
    )
