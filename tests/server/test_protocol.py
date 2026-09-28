"""Connection handshake, admission gates, request correlation, and task bounds."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from pi_agent.protocol import (
    FrameDecoder,
    decode_server_message,
    encode_client_message,
    encode_frame,
)
from pi_agent.protocol.messages import (
    PROTOCOL_VERSION,
    ClientHello,
    ClientRequest,
    ProtocolError,
    RunStartedEvent,
    ServerEvent,
    ServerHello,
    ServerHelloError,
    ServerResponse,
)
from pi_agent.server.connection import ServerConnection


class MemoryByteConnection:
    def __init__(self) -> None:
        self._chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.sent: list[bytes] = []
        self.closed = False
        self.sent_event = asyncio.Event()

    async def read(self, max_bytes: int) -> bytes:
        del max_bytes
        value = await self._chunks.get()
        return value or b""

    async def send(self, data: bytes) -> None:
        assert not self.closed
        self.sent.append(data)
        self.sent_event.set()

    async def close(self) -> None:
        self.closed = True

    def feed(self, data: bytes) -> None:
        self._chunks.put_nowait(data)

    def finish(self) -> None:
        self._chunks.put_nowait(None)

    async def wait_for_sent(self, count: int) -> None:
        while len(self.sent) < count:
            self.sent_event.clear()
            await asyncio.wait_for(self.sent_event.wait(), timeout=1)


class RecordingDispatcher:
    def __init__(self) -> None:
        self.request_ids: list[int] = []
        self.started: dict[int, asyncio.Event] = {}
        self.release: dict[int, asyncio.Event] = {}

    async def dispatch_message(
        self,
        request: ClientRequest,
        *,
        send_event: Callable[[ServerEvent], Awaitable[None]],
    ) -> ServerResponse:
        del send_event
        request_id = request.request_id
        self.request_ids.append(request_id)
        self.started.setdefault(request_id, asyncio.Event()).set()
        await self.release.setdefault(request_id, asyncio.Event()).wait()
        return ServerResponse(
            type="response",
            request_id=request_id,
            command=request.request.command,
            ok=True,
        )

    async def cancel_owned_run(self, session_id: str, run_id: str, /) -> None:
        del session_id, run_id


def _frames(messages: Iterable[object]) -> bytes:
    return b"".join(
        encode_frame(encode_client_message(message))  # type: ignore[arg-type]
        for message in messages
    )


def _decode_sent(connection: MemoryByteConnection) -> list[object]:
    decoder = FrameDecoder()
    payloads = [payload for data in connection.sent for payload in decoder.feed(data)]
    return [decode_server_message(payload) for payload in payloads]


def test_valid_hello_moves_connection_to_ready_then_closed_on_eof() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        server = ServerConnection(connection, RecordingDispatcher(), server_epoch="epoch-1")
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=PROTOCOL_VERSION)]))
        await connection.wait_for_sent(1)
        connection.finish()
        await task

        assert _decode_sent(connection) == [
            ServerHello(type="hello", version=1, server_epoch="epoch-1")
        ]
        assert server.phase == "closed"

    asyncio.run(scenario())


def test_request_before_hello_is_rejected_without_dispatch() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = RecordingDispatcher()
        server = ServerConnection(connection, dispatcher, server_epoch="epoch-1")
        request = ClientRequest.model_validate(
            {"type": "request", "request_id": 1, "request": {"command": "create_session"}}
        )
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([request]))
        await task
        messages = _decode_sent(connection)

        assert len(messages) == 1
        assert isinstance(messages[0], ServerResponse)
        assert messages[0].error == ProtocolError(
            code="invalid_request", message="Hello is required first."
        )
        assert dispatcher.request_ids == []
        assert server.phase == "closed"

    asyncio.run(scenario())


def test_unknown_protocol_version_returns_hello_error_and_closes() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        server = ServerConnection(connection, RecordingDispatcher(), server_epoch="epoch-1")
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=99)]))
        await task
        messages = _decode_sent(connection)

        assert len(messages) == 1
        assert isinstance(messages[0], ServerHelloError)
        assert messages[0].error.code == "unsupported_version"
        assert server.phase == "closed"

    asyncio.run(scenario())


def test_duplicate_hello_is_rejected_after_one_successful_handshake() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        server = ServerConnection(connection, RecordingDispatcher(), server_epoch="epoch-1")
        task = asyncio.create_task(server.serve())
        hello = ClientHello(type="hello", version=PROTOCOL_VERSION)
        connection.feed(_frames([hello, hello]))
        await task
        messages = _decode_sent(connection)

        assert isinstance(messages[0], ServerHello)
        assert isinstance(messages[1], ServerHelloError)
        assert messages[1].error.code == "invalid_request"

    asyncio.run(scenario())


def test_duplicate_request_id_closes_connection_without_second_dispatch() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = RecordingDispatcher()
        server = ServerConnection(connection, dispatcher, server_epoch="epoch-1")
        hello = ClientHello(type="hello", version=PROTOCOL_VERSION)
        request = ClientRequest.model_validate(
            {"type": "request", "request_id": 1, "request": {"command": "create_session"}}
        )
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([hello, request, request]))
        await task

        assert dispatcher.request_ids == []
        assert _decode_sent(connection) == [
            ServerHello(type="hello", version=1, server_epoch="epoch-1")
        ]
        assert server.phase == "closed"

    asyncio.run(scenario())


def test_two_requests_may_finish_out_of_order_without_crossing_ids() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = RecordingDispatcher()
        server = ServerConnection(connection, dispatcher, server_epoch="epoch-1")
        first = ClientRequest.model_validate(
            {"type": "request", "request_id": 1, "request": {"command": "create_session"}}
        )
        second = ClientRequest.model_validate(
            {"type": "request", "request_id": 2, "request": {"command": "create_session"}}
        )
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=1), first, second]))
        await asyncio.wait_for(dispatcher.started.setdefault(1, asyncio.Event()).wait(), timeout=1)
        await asyncio.wait_for(dispatcher.started.setdefault(2, asyncio.Event()).wait(), timeout=1)
        dispatcher.release.setdefault(2, asyncio.Event()).set()
        await connection.wait_for_sent(2)
        dispatcher.release.setdefault(1, asyncio.Event()).set()
        await connection.wait_for_sent(3)
        connection.finish()
        await task
        messages = _decode_sent(connection)

        assert [
            message.request_id for message in messages if isinstance(message, ServerResponse)
        ] == [2, 1]

    asyncio.run(scenario())


def test_per_connection_in_flight_limit_returns_busy() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = RecordingDispatcher()
        server = ServerConnection(
            connection,
            dispatcher,
            server_epoch="epoch-1",
            max_in_flight=1,
        )
        first = ClientRequest.model_validate(
            {"type": "request", "request_id": 1, "request": {"command": "create_session"}}
        )
        second = ClientRequest.model_validate(
            {"type": "request", "request_id": 2, "request": {"command": "create_session"}}
        )
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=1), first, second]))
        await asyncio.wait_for(dispatcher.started.setdefault(1, asyncio.Event()).wait(), timeout=1)
        await connection.wait_for_sent(2)
        messages = _decode_sent(connection)
        busy = next(message for message in messages if isinstance(message, ServerResponse))
        assert busy.request_id == 2
        assert busy.error is not None and busy.error.code == "busy"
        assert dispatcher.request_ids == [1]
        connection.finish()
        await task

    asyncio.run(scenario())


def test_disconnect_cancels_pending_work_and_prevents_late_send() -> None:
    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = RecordingDispatcher()
        server = ServerConnection(connection, dispatcher, server_epoch="epoch-1")
        request = ClientRequest.model_validate(
            {"type": "request", "request_id": 1, "request": {"command": "create_session"}}
        )
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=1), request]))
        connection.finish()
        await task
        sent_count = len(connection.sent)
        await asyncio.sleep(0)

        assert server.phase == "closed"
        assert len(connection.sent) == sent_count
        assert sent_count == 1

    asyncio.run(scenario())


def test_disconnect_uses_coordinator_boundary_for_started_run_cleanup() -> None:
    class OwnedRunDispatcher(RecordingDispatcher):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup: list[tuple[str, str]] = []
            self.finish_run = asyncio.Event()

        async def dispatch_message(
            self,
            request: ClientRequest,
            *,
            send_event: Callable[[ServerEvent], Awaitable[None]],
        ) -> ServerResponse:
            await send_event(
                RunStartedEvent(
                    type="event",
                    event="run_started",
                    request_id=request.request_id,
                    session_id="session-1",
                    run_id="run-1",
                )
            )
            await self.finish_run.wait()
            return ServerResponse(
                type="response",
                request_id=request.request_id,
                command=request.request.command,
                ok=True,
            )

        async def cancel_owned_run(self, session_id: str, run_id: str, /) -> None:
            self.cleanup.append((session_id, run_id))
            self.finish_run.set()

    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = OwnedRunDispatcher()
        server = ServerConnection(connection, dispatcher, server_epoch="epoch-1")
        request = ClientRequest.model_validate(
            {
                "type": "request",
                "request_id": 1,
                "request": {
                    "command": "prompt",
                    "session_id": "session-1",
                    "text": "Read probe.txt",
                },
            }
        )
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=1), request]))
        await connection.wait_for_sent(2)
        connection.finish()
        await task

        assert dispatcher.cleanup == [("session-1", "run-1")]
        assert server.phase == "closed"
        assert len(connection.sent) == 2

    asyncio.run(scenario())


def test_disconnect_does_not_start_run_after_owned_run_cleanup_snapshot() -> None:
    class RacingDispatcher(RecordingDispatcher):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_started = asyncio.Event()
            self.allow_cleanup = asyncio.Event()
            self.release_second_event = asyncio.Event()
            self.cleanup: list[tuple[str, str]] = []
            self.second_run_continued = False

        async def dispatch_message(
            self,
            request: ClientRequest,
            *,
            send_event: Callable[[ServerEvent], Awaitable[None]],
        ) -> ServerResponse:
            self.request_ids.append(request.request_id)
            self.started.setdefault(request.request_id, asyncio.Event()).set()
            run_id = f"run-{request.request_id}"
            if request.request_id == 2:
                await self.release_second_event.wait()
            await send_event(
                RunStartedEvent(
                    type="event",
                    event="run_started",
                    request_id=request.request_id,
                    session_id=f"session-{request.request_id}",
                    run_id=run_id,
                )
            )
            if request.request_id == 2:
                self.second_run_continued = True
            else:
                await asyncio.Event().wait()
            return ServerResponse(
                type="response",
                request_id=request.request_id,
                command=request.request.command,
                ok=True,
            )

        async def cancel_owned_run(self, session_id: str, run_id: str, /) -> None:
            self.cleanup.append((session_id, run_id))
            self.cleanup_started.set()
            await self.allow_cleanup.wait()

    async def scenario() -> None:
        connection = MemoryByteConnection()
        dispatcher = RacingDispatcher()
        server = ServerConnection(connection, dispatcher, server_epoch="epoch-1")
        requests = [
            ClientRequest.model_validate(
                {
                    "type": "request",
                    "request_id": request_id,
                    "request": {
                        "command": "prompt",
                        "session_id": f"session-{request_id}",
                        "text": "hello",
                    },
                }
            )
            for request_id in (1, 2)
        ]
        task = asyncio.create_task(server.serve())
        connection.feed(_frames([ClientHello(type="hello", version=1), requests[0]]))
        await connection.wait_for_sent(2)
        connection.feed(_frames([requests[1]]))
        await asyncio.wait_for(dispatcher.started.setdefault(2, asyncio.Event()).wait(), timeout=1)
        connection.finish()

        await asyncio.wait_for(dispatcher.cleanup_started.wait(), timeout=1)
        assert str(server.phase) == "closing"
        dispatcher.release_second_event.set()
        await asyncio.sleep(0)
        dispatcher.allow_cleanup.set()
        await task

        assert dispatcher.cleanup == [("session-1", "run-1")]
        assert dispatcher.second_run_continued is False
        assert str(server.phase) == "closed"

    asyncio.run(scenario())
