"""Request futures, response correlation, deadlines, and uncertain outcomes."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from pi_agent.client.client import RemoteClient
from pi_agent.client.errors import (
    ClientProtocolError,
    RequestOutcomeUnknownError,
    ServerRejectedError,
)
from pi_agent.protocol import (
    FrameDecoder,
    decode_client_message,
    decode_server_message,
    encode_frame,
    encode_server_message,
)
from pi_agent.protocol.messages import (
    Cancel,
    ClientHello,
    ClientMessage,
    ClientRequest,
    DisplayMessage,
    GetSnapshot,
    Prompt,
    ProtocolError,
    ServerHello,
    ServerMessage,
    ServerResponse,
    SessionSnapshot,
)


class MemoryEndpoint:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.peer: MemoryEndpoint | None = None
        self.closed = False

    async def read(self, max_bytes: int) -> bytes:
        del max_bytes
        return await self.incoming.get()

    async def send(self, data: bytes) -> None:
        peer = self.peer
        if self.closed or peer is None or peer.closed:
            raise ConnectionError("memory stream is closed")
        peer.incoming.put_nowait(data)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.incoming.put_nowait(b"")
        peer = self.peer
        if peer is not None and not peer.closed:
            peer.incoming.put_nowait(b"")


def memory_pair() -> tuple[MemoryEndpoint, MemoryEndpoint]:
    client = MemoryEndpoint()
    server = MemoryEndpoint()
    client.peer = server
    server.peer = client
    return client, server


RequestHandler = Callable[[ClientRequest], Awaitable[None]]


class ProtocolPeer:
    def __init__(self, transport: MemoryEndpoint, on_request: RequestHandler) -> None:
        self.transport = transport
        self.on_request = on_request
        self.task: asyncio.Task[None] | None = None
        self._request_tasks: set[asyncio.Future[None]] = set()

    def start(self) -> None:
        self.task = asyncio.create_task(self._serve())

    async def close(self) -> None:
        await self.transport.close()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
        if self._request_tasks:
            await asyncio.gather(*self._request_tasks, return_exceptions=True)

    async def send(self, message: ServerMessage) -> None:
        await self.transport.send(encode_frame(encode_server_message(message)))

    async def _serve(self) -> None:
        decoder = FrameDecoder()
        try:
            while True:
                chunk = await self.transport.read(64 * 1024)
                if not chunk:
                    decoder.finish()
                    return
                for payload in decoder.feed(chunk):
                    message: ClientMessage = decode_client_message(payload)
                    if isinstance(message, ClientHello):
                        await self.send(
                            ServerHello(type="hello", version=1, server_epoch="epoch-1")
                        )
                    else:
                        task = asyncio.ensure_future(self.on_request(message))
                        self._request_tasks.add(task)
                        task.add_done_callback(self._request_tasks.discard)
        except (ConnectionError, asyncio.CancelledError):
            return


def _snapshot(session_id: str, revision: int = 1) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session_id,
        server_epoch="epoch-1",
        revision=revision,
        checkpoint_id=None,
        graph_status="idle",
        run_phase="idle",
        run_outcome=None,
        active_run_id=None,
        message_count=1,
        messages=(DisplayMessage(message_id="message-1", role="assistant", text="ready"),),
        truncated=False,
    )


def _success(request: ClientRequest, session_id: str | None = None) -> ServerResponse:
    command = request.request.command
    if session_id is None:
        request_body = request.request
        if isinstance(request_body, (GetSnapshot, Prompt, Cancel)):
            session_id = request_body.session_id
        else:
            session_id = "created-session"
    return ServerResponse(
        type="response",
        request_id=request.request_id,
        command=command,
        ok=True,
        snapshot=_snapshot(session_id),
    )


async def _factory(transport: MemoryEndpoint) -> MemoryEndpoint:
    return transport


def test_out_of_order_responses_resolve_their_matching_request() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()
        received: asyncio.Queue[ClientRequest] = asyncio.Queue()

        async def queue_request(request: ClientRequest) -> None:
            received.put_nowait(request)

        peer = ProtocolPeer(server_stream, queue_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        create_task = asyncio.create_task(client.create_session())
        snapshot_task = asyncio.create_task(client.get_snapshot("session-2"))
        first = await received.get()
        second = await received.get()

        await peer.send(_success(second))
        await peer.send(_success(first))

        results = await asyncio.gather(create_task, snapshot_task)
        assert results[0].session_id == "created-session"
        assert results[1].session_id == "session-2"
        await client.close()
        await peer.close()

    asyncio.run(scenario())


def test_prompt_and_cancel_methods_send_their_typed_commands() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()
        received: asyncio.Queue[ClientRequest] = asyncio.Queue()

        async def queue_request(request: ClientRequest) -> None:
            received.put_nowait(request)

        peer = ProtocolPeer(server_stream, queue_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        prompt_task = asyncio.create_task(client.prompt("session-1", "read the file"))
        cancel_task = asyncio.create_task(client.cancel("session-1", "run-1"))
        prompt_request = await received.get()
        cancel_request = await received.get()

        assert prompt_request.request.command == "prompt"
        assert cancel_request.request.command == "cancel"
        await peer.send(_success(cancel_request))
        await peer.send(_success(prompt_request))
        await asyncio.gather(prompt_task, cancel_task)
        await client.close()
        await peer.close()

    asyncio.run(scenario())


def test_response_command_mismatch_fails_the_request_and_connection() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()
        requests: asyncio.Queue[ClientRequest] = asyncio.Queue()

        async def queue_request(request: ClientRequest) -> None:
            requests.put_nowait(request)

        peer = ProtocolPeer(server_stream, queue_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        request_task = asyncio.create_task(client.create_session())
        request = await requests.get()
        response = _success(request).model_copy(update={"command": "prompt"})
        await peer.send(response)

        with pytest.raises(ClientProtocolError, match="command"):
            await request_task
        await peer.close()

    asyncio.run(scenario())


def test_server_command_error_is_returned_as_typed_safe_error() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()
        requests: asyncio.Queue[ClientRequest] = asyncio.Queue()

        async def queue_request(request: ClientRequest) -> None:
            requests.put_nowait(request)

        peer = ProtocolPeer(server_stream, queue_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        request_task = asyncio.create_task(client.get_snapshot("missing"))
        request = await requests.get()
        await peer.send(
            ServerResponse(
                type="response",
                request_id=request.request_id,
                command=request.request.command,
                ok=False,
                error=ProtocolError(code="not_found", message="Session was not found."),
            )
        )

        with pytest.raises(ServerRejectedError) as failure:
            await request_task
        assert failure.value.code == "not_found"
        assert failure.value.safe_message == "Session was not found."
        await client.close()
        await peer.close()

    asyncio.run(scenario())


def test_disconnect_rejects_pending_work_as_outcome_unknown_and_stales_cache() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()
        requests: asyncio.Queue[ClientRequest] = asyncio.Queue()

        async def queue_request(request: ClientRequest) -> None:
            requests.put_nowait(request)

        peer = ProtocolPeer(server_stream, queue_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        generation = client.state.connection_generation
        client.state.accept_server_epoch(generation, "epoch-1")
        client.state.apply_snapshot(_snapshot("created-session"), generation)
        request_task = asyncio.create_task(client.get_snapshot("created-session"))
        await requests.get()
        await peer.close()

        with pytest.raises(RequestOutcomeUnknownError, match="unknown"):
            await request_task
        assert client.state.is_stale("created-session")

    asyncio.run(scenario())


def test_timeout_closes_connection_and_reports_unknown_outcome() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()

        async def ignore_request(_request: ClientRequest) -> None:
            return None

        peer = ProtocolPeer(server_stream, ignore_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=0.02)
        await client.connect()

        with pytest.raises(RequestOutcomeUnknownError, match="timed out"):
            await client.create_session()
        assert not client.connected
        await peer.close()

    asyncio.run(scenario())


def test_unknown_response_id_fails_connection_without_matching_a_future() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()

        async def ignore_request(_request: ClientRequest) -> None:
            return None

        peer = ProtocolPeer(server_stream, ignore_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        connection = client._connection
        response = ServerResponse(
            type="response",
            request_id=999,
            command="create_session",
            ok=True,
            snapshot=_snapshot("ghost"),
        )
        encoded_response = encode_server_message(response)
        assert decode_server_message(encoded_response) == response
        await peer.send(response)
        await _wait_until_disconnected(client)

        assert not client.connected
        assert connection is not None
        assert isinstance(connection.failure, ClientProtocolError)
        await peer.close()

    asyncio.run(scenario())


def test_duplicate_response_fails_connection_after_resolving_once() -> None:
    async def scenario() -> None:
        client_stream, server_stream = memory_pair()
        requests: asyncio.Queue[ClientRequest] = asyncio.Queue()

        async def queue_request(request: ClientRequest) -> None:
            requests.put_nowait(request)

        peer = ProtocolPeer(server_stream, queue_request)
        peer.start()
        client = RemoteClient(lambda: _factory(client_stream), request_timeout_seconds=2)
        await client.connect()
        request_task = asyncio.create_task(client.create_session())
        request = await requests.get()
        response = _success(request)
        await peer.send(response)
        result = await request_task
        assert result.session_id == "created-session"

        await peer.send(response)
        await _wait_until_disconnected(client)
        assert not client.connected
        await peer.close()

    asyncio.run(scenario())


async def _wait_until_disconnected(client: RemoteClient) -> None:
    for _ in range(100):
        if not client.connected:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("client connection did not fail for an unmatched response")
