"""Client-side hello negotiation and the single protocol receive loop."""

import asyncio
from collections.abc import Callable

from pi_agent.client.errors import (
    ClientDisconnectedError,
    ClientProtocolError,
    UnsupportedProtocolVersionError,
)
from pi_agent.protocol import (
    DEFAULT_MAX_FRAME_BYTES,
    FrameDecoder,
    FrameError,
    ProtocolValidationError,
    decode_server_message,
    encode_client_message,
    encode_frame,
)
from pi_agent.protocol.messages import (
    PROTOCOL_VERSION,
    ClientHello,
    ClientRequest,
    ServerEvent,
    ServerHello,
    ServerHelloError,
    ServerMessage,
    ServerResponse,
)
from pi_agent.protocol.transport import AsyncByteConnection

READ_CHUNK_BYTES = 64 * 1024
MessageHandler = Callable[[ServerResponse | ServerEvent], None]
HelloHandler = Callable[[ServerHello], None]
DisconnectHandler = Callable[[ClientDisconnectedError], None]


class ClientConnection:
    """Own one authenticated byte stream, hello exchange, and read task."""

    def __init__(
        self,
        transport: AsyncByteConnection,
        *,
        on_message: MessageHandler,
        on_hello: HelloHandler,
        on_disconnect: DisconnectHandler,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        handshake_timeout_seconds: float = 5.0,
    ) -> None:
        self._transport = transport
        self._on_message = on_message
        self._on_hello = on_hello
        self._on_disconnect = on_disconnect
        self._max_frame_bytes = max_frame_bytes
        self._handshake_timeout_seconds = handshake_timeout_seconds
        self._hello_future: asyncio.Future[ServerHello] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._hello: ServerHello | None = None
        self._closed = False
        self._protocol_failure: ClientProtocolError | None = None
        self._failure: ClientDisconnectedError | None = None

    @property
    def connected(self) -> bool:
        return self._hello is not None and not self._closed

    @property
    def server_epoch(self) -> str | None:
        return self._hello.server_epoch if self._hello is not None else None

    @property
    def failure(self) -> ClientDisconnectedError | None:
        return self._failure

    async def start(self) -> ServerHello:
        """Send hello, start one receive loop, and wait within its deadline."""
        if self._reader_task is not None or self._closed:
            raise ClientDisconnectedError("Client connection cannot be started.")
        self._hello_future = asyncio.get_running_loop().create_future()
        self._reader_task = asyncio.create_task(self._read_loop())
        try:
            hello = ClientHello(type="hello", version=PROTOCOL_VERSION)
            await self._transport.send(
                encode_frame(
                    encode_client_message(hello, max_payload_bytes=self._max_frame_bytes),
                    max_frame_bytes=self._max_frame_bytes,
                )
            )
            async with asyncio.timeout(self._handshake_timeout_seconds):
                self._hello = await self._hello_future
            return self._hello
        except TimeoutError as error:
            failure = ClientProtocolError("Server hello deadline exceeded.")
            await self.close(failure)
            raise failure from error
        except asyncio.CancelledError:
            await self.close(ClientDisconnectedError("Client handshake was cancelled."))
            raise
        except Exception:
            await self.close(ClientDisconnectedError("Client handshake failed."))
            raise

    async def send_request(self, request: ClientRequest) -> None:
        """Encode and send one validated request over the ordered stream."""
        if not self.connected:
            raise ClientDisconnectedError("Client is not connected.")
        try:
            payload = encode_client_message(request, max_payload_bytes=self._max_frame_bytes)
            await self._transport.send(encode_frame(payload, max_frame_bytes=self._max_frame_bytes))
        except Exception as error:
            failure = ClientDisconnectedError("Client request could not be sent.")
            await self.close(failure)
            raise failure from error

    async def close(self, error: ClientDisconnectedError | None = None) -> None:
        """Close once, stop the reader, and notify the owning client."""
        if self._closed:
            return
        failure = error or ClientDisconnectedError("Client disconnected.")
        self._closed = True
        self._failure = failure
        current = asyncio.current_task()
        task = self._reader_task
        if task is not None and task is not current and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await self._transport.close()
        finally:
            future = self._hello_future
            if future is not None and not future.done():
                future.set_exception(failure)
            self._on_disconnect(failure)

    def fail(self, error: ClientProtocolError) -> None:
        """Mark the connection for teardown after the current message callback."""
        if not self._closed:
            self._protocol_failure = error

    async def _read_loop(self) -> None:
        decoder = FrameDecoder(max_frame_bytes=self._max_frame_bytes)
        try:
            while not self._closed:
                chunk = await self._transport.read(READ_CHUNK_BYTES)
                if not chunk:
                    decoder.finish()
                    raise ClientDisconnectedError("Server closed the connection.")
                for payload in decoder.feed(chunk):
                    message = decode_server_message(
                        payload,
                        max_payload_bytes=self._max_frame_bytes,
                    )
                    self._accept_message(message)
                    if self._protocol_failure is not None:
                        raise self._protocol_failure
        except asyncio.CancelledError:
            raise
        except ClientProtocolError as error:
            await self._finish(error)
        except (FrameError, ProtocolValidationError):
            await self._finish(ClientProtocolError("Server sent an invalid protocol message."))
        except ClientDisconnectedError as error:
            await self._finish(error)
        except Exception:
            await self._finish(ClientDisconnectedError("Client receive loop failed."))

    def _accept_message(self, message: ServerMessage) -> None:
        future = self._hello_future
        if future is None:
            raise ClientProtocolError("Client handshake has not started.")
        if not future.done():
            if isinstance(message, ServerHello):
                self._on_hello(message)
                future.set_result(message)
                return
            if isinstance(message, ServerHelloError):
                if message.error.code == "unsupported_version":
                    failure: ClientProtocolError = UnsupportedProtocolVersionError(
                        message.error.message
                    )
                else:
                    failure = ClientProtocolError(message.error.message)
                future.set_exception(failure)
                raise failure
            raise ClientProtocolError("Expected server hello before other messages.")
        if isinstance(message, (ServerHello, ServerHelloError)):
            raise ClientProtocolError("Server hello may only be sent once.")
        self._on_message(message)

    async def _finish(self, error: ClientDisconnectedError) -> None:
        if self._closed:
            return
        await self.close(error)
