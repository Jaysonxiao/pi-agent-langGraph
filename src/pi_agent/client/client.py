"""Small async API for the authenticated remote session protocol."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeAlias

from pi_agent.client.connection import ClientConnection
from pi_agent.client.errors import (
    ClientDisconnectedError,
    ClientProtocolError,
    RequestOutcomeUnknownError,
    ServerRejectedError,
)
from pi_agent.client.state import ClientState
from pi_agent.protocol.messages import (
    MAX_REQUEST_ID,
    Cancel,
    ClientCommand,
    ClientRequest,
    CreateSession,
    GetSnapshot,
    Prompt,
    ServerEvent,
    ServerHello,
    ServerResponse,
    SessionRemovedEvent,
    SessionSnapshot,
    SnapshotEvent,
)
from pi_agent.protocol.transport import AsyncByteConnection

TransportFactory: TypeAlias = Callable[[], Awaitable[AsyncByteConnection]]
EventListener: TypeAlias = Callable[[ServerEvent], None]


@dataclass(slots=True)
class _PendingRequest:
    command: str
    generation: int
    future: asyncio.Future[SessionSnapshot]


class RemoteClient:
    """Own request correlation and authoritative cached snapshots."""

    def __init__(
        self,
        transport_factory: TransportFactory,
        *,
        request_timeout_seconds: float = 30.0,
        handshake_timeout_seconds: float = 5.0,
    ) -> None:
        _validate_timeout(request_timeout_seconds, "request_timeout_seconds")
        _validate_timeout(handshake_timeout_seconds, "handshake_timeout_seconds")
        self._transport_factory = transport_factory
        self._request_timeout_seconds = request_timeout_seconds
        self._handshake_timeout_seconds = handshake_timeout_seconds
        self._state = ClientState()
        self._connection: ClientConnection | None = None
        self._generation = 0
        self._request_sequence = 0
        self._pending: dict[int, _PendingRequest] = {}
        self._event_listeners: set[EventListener] = set()

    @property
    def state(self) -> ClientState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._connection is not None and self._connection.connected

    async def connect(self) -> ServerHello:
        """Open a fresh authenticated stream and negotiate the protocol hello."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        generation = self._state.begin_connection()
        self._generation = generation
        try:
            transport = await self._transport_factory()
        except Exception as error:
            self._state.mark_disconnected(generation)
            raise ClientDisconnectedError("Client transport could not be created.") from error

        connection = ClientConnection(
            transport,
            on_message=lambda message: self._handle_message(message, generation),
            on_hello=lambda hello: _accept_hello(self._state, generation, hello),
            on_disconnect=lambda error: self._handle_disconnect(error, generation),
            handshake_timeout_seconds=self._handshake_timeout_seconds,
        )
        self._connection = connection
        try:
            return await connection.start()
        except Exception:
            if self._connection is connection:
                self._connection = None
            raise

    async def reconnect(self) -> ServerHello:
        return await self.connect()

    async def close(self) -> None:
        connection = self._connection
        if connection is not None:
            await connection.close()

    def subscribe_events(self, listener: EventListener) -> Callable[[], None]:
        self._event_listeners.add(listener)

        def unsubscribe() -> None:
            self._event_listeners.discard(listener)

        return unsubscribe

    async def create_session(self) -> SessionSnapshot:
        return await self._request(CreateSession(command="create_session"))

    async def get_snapshot(self, session_id: str) -> SessionSnapshot:
        return await self._request(GetSnapshot(command="get_snapshot", session_id=session_id))

    async def prompt(self, session_id: str, text: str) -> SessionSnapshot:
        return await self._request(Prompt(command="prompt", session_id=session_id, text=text))

    async def cancel(self, session_id: str, run_id: str) -> SessionSnapshot:
        return await self._request(Cancel(command="cancel", session_id=session_id, run_id=run_id))

    async def _request(self, command: ClientCommand) -> SessionSnapshot:
        connection = self._connection
        if connection is None or not connection.connected:
            raise ClientDisconnectedError("Client is not connected.")
        if self._request_sequence >= MAX_REQUEST_ID:
            raise ClientProtocolError("Client request ID space is exhausted.")
        self._request_sequence += 1
        request_id = self._request_sequence
        future: asyncio.Future[SessionSnapshot] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(
            command=command.command,
            generation=self._generation,
            future=future,
        )
        request = ClientRequest(type="request", request_id=request_id, request=command)

        try:
            await connection.send_request(request)
        except ClientDisconnectedError:
            if not future.done():
                future.set_exception(
                    RequestOutcomeUnknownError("The request may have reached the server.")
                )
        try:
            async with asyncio.timeout(self._request_timeout_seconds):
                return await future
        except TimeoutError as error:
            failure = RequestOutcomeUnknownError(
                "The request timed out; its server-side outcome is unknown."
            )
            current = self._connection
            if current is not None:
                await current.close(failure)
            raise failure from error
        finally:
            self._pending.pop(request_id, None)

    def resolve_response(
        self,
        response: ServerResponse,
        *,
        connection_generation: int,
    ) -> None:
        """按 request ID 结算 pending 请求,并应用当前连接的权威快照。"""
        # 旧连接的迟到数据不能影响新连接中的 pending 请求或缓存状态。
        if connection_generation != self._generation:
            return

        pending = self._pending.get(response.request_id)
        if pending is None or pending.generation != connection_generation:
            # ID 不存在通常表示重复响应或服务端响应了未知请求,必须终止当前连接。
            failure = ClientProtocolError("Response request ID is unknown or already completed.")
            connection = self._connection
            if connection is not None:
                connection.fail(failure)
            return
        # 从 pending 表移除后,本响应就成为唯一能够结算此请求的响应。
        self._pending.pop(response.request_id)

        if pending.future.done():
            failure = ClientProtocolError("Response matched an already completed request.")
            connection = self._connection
            if connection is not None:
                connection.fail(failure)
            return

        if response.command != pending.command:
            # 先将明确关联的 future 以协议错误结束,再安排当前连接关闭。
            failure = ClientProtocolError("Response command does not match request command.")
            pending.future.set_exception(failure)
            connection = self._connection
            if connection is not None:
                connection.fail(failure)
            return

        if not response.ok:
            if response.error is None:
                failure = ClientProtocolError("Failed response is missing its protocol error.")
                pending.future.set_exception(failure)
                connection = self._connection
                if connection is not None:
                    connection.fail(failure)
                return
            # 服务端错误文案属于协议安全字段,交由专用异常原样提供给调用方。
            pending.future.set_exception(ServerRejectedError(response.error))
            return

        snapshot = response.snapshot
        if snapshot is None:
            failure = ClientProtocolError("Successful response is missing its snapshot.")
            pending.future.set_exception(failure)
            connection = self._connection
            if connection is not None:
                connection.fail(failure)
            return

        # ClientState 会拒绝旧 revision;future 仍返回本次响应关联的快照结果。
        self._state.apply_snapshot(snapshot, connection_generation)
        pending.future.set_result(snapshot)

    def _handle_message(
        self,
        message: ServerResponse | ServerEvent,
        connection_generation: int,
    ) -> None:
        if connection_generation != self._generation:
            return
        if isinstance(message, ServerResponse):
            self.resolve_response(message, connection_generation=connection_generation)
            return
        if isinstance(message, SnapshotEvent):
            self._state.apply_event(message, connection_generation)
        elif isinstance(message, SessionRemovedEvent):
            self._state.clear_session(message.session_id)
        else:
            self._state.apply_event(message, connection_generation)
        for listener in tuple(self._event_listeners):
            try:
                listener(message)
            except Exception:
                # Listener failures must not break protocol bookkeeping.
                continue

    def _handle_disconnect(
        self,
        error: ClientDisconnectedError,
        generation: int,
    ) -> None:
        if generation != self._generation:
            return
        self._state.mark_disconnected(generation)
        self._connection = None
        for request_id, pending in tuple(self._pending.items()):
            if pending.generation != generation:
                continue
            self._pending.pop(request_id, None)
            if not pending.future.done():
                pending.future.set_exception(
                    RequestOutcomeUnknownError(
                        f"Request outcome is unknown after disconnect: {error}"
                    )
                )


def _validate_timeout(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{name} must be a positive finite number.")


def _accept_hello(state: ClientState, generation: int, hello: ServerHello) -> None:
    state.accept_server_epoch(generation, hello.server_epoch)
