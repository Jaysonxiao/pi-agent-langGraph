"""Public loopback server composition root for M10.8."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import TextIO, TypeAlias
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.config import ModelOptions, resolve_model_config
from pi_agent.models.http_client import build_async_provider_client
from pi_agent.protocol.transport import LOOPBACK_HOST
from pi_agent.server.connection import ByteConnection, ServerConnection
from pi_agent.server.dispatcher import ServerCommandService, ServerDispatcher
from pi_agent.server.runtime import ServerSessionRuntime
from pi_agent.server.sessions import SessionCoordinator
from pi_agent.server.transports.tcp import TcpByteServer
from pi_agent.sessions.metadata import SqliteSessionCatalog

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CANCELLED = 130
SignalHandler: TypeAlias = Callable[[int, FrameType | None], object] | int | None


@dataclass(frozen=True, slots=True)
class ServerOptions:
    """Non-secret settings owned by the server process."""

    workspace: Path
    database: Path
    provider: str | None = None
    host: str = LOOPBACK_HOST
    port: int = 8765


class ServerApplication:
    """Own the TCP listener, dispatcher dependencies, and model lifecycle."""

    def __init__(
        self,
        *,
        options: ServerOptions,
        dispatcher: ServerDispatcher,
        server_epoch: str,
        close_model: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.options = options
        self.dispatcher = dispatcher
        self.server_epoch = server_epoch
        self._tcp: TcpByteServer | None = None
        self._close_model = close_model
        self._closed = False

    @property
    def port(self) -> int:
        """Return the bound port, including an OS-selected port when configured as 0."""
        if self._tcp is None:
            raise RuntimeError("Server application has not started.")
        return self._tcp.port

    async def start(self) -> int:
        """Bind the loopback listener and return its effective port."""
        if self._closed or self._tcp is not None:
            raise RuntimeError("Server application cannot be started in its current state.")

        async def handle(connection: ByteConnection) -> None:
            protocol = ServerConnection(
                connection,
                self.dispatcher,
                server_epoch=self.server_epoch,
            )
            await protocol.serve()

        self._tcp = await TcpByteServer.start(
            handle,
            host=self.options.host,
            port=self.options.port,
        )
        return self._tcp.port

    async def close(self) -> None:
        """Stop accepting peers and close owned model resources exactly once."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._tcp is not None:
                await self._tcp.close()
        finally:
            if self._close_model is not None:
                await self._close_model()


def create_server_application(
    options: ServerOptions,
    *,
    environ: Mapping[str, str] | None = None,
) -> ServerApplication:
    """Resolve server-owned settings and assemble runtime behind protocol ports."""
    environment = os.environ if environ is None else environ
    if not options.workspace.is_dir():
        raise ValueError("Workspace must be an existing directory.")
    if options.database.exists() and not options.database.is_file():
        raise ValueError("Database path must be a file.")
    options.database.parent.mkdir(parents=True, exist_ok=True)

    model_config = resolve_model_config(ModelOptions(provider=options.provider), environment)
    close_model: Callable[[], Awaitable[None]] | None = None
    if model_config.provider == "fake":
        model: AsyncChatModel = _FakeReadModel()
    else:
        model = CompatibleAsyncChatModel(build_async_provider_client(model_config))
        close_model = model.aclose

    server_epoch = uuid4().hex
    runtime = ServerSessionRuntime(model=model, server_epoch=server_epoch)
    service = ServerCommandService(
        runtime=runtime,
        catalog=SqliteSessionCatalog(options.database),
        coordinator=SessionCoordinator(),
        database=options.database,
        workspace=options.workspace,
    )
    return ServerApplication(
        options=options,
        dispatcher=ServerDispatcher(service),
        server_epoch=server_epoch,
        close_model=close_model,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pi-agent-server")
    parser.add_argument("--provider", choices=("fake", "compatible"))
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=Path(".pi-agent/sessions.sqlite"))
    parser.add_argument("--host", default=LOOPBACK_HOST)
    parser.add_argument("--port", type=int, default=8765)
    return parser


async def _serve_until_stopped(
    app: ServerApplication,
    stopping: asyncio.Event,
    output: TextIO,
) -> None:
    try:
        port = await app.start()
        output.write(json.dumps({"event": "ready", "host": app.options.host, "port": port}) + "\n")
        output.flush()
        await stopping.wait()
    finally:
        await app.close()


async def _run_server(options: ServerOptions, output: TextIO) -> None:
    app = create_server_application(options)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[tuple[signal.Signals, SignalHandler, bool]] = []
    signals = [signal.SIGINT, signal.SIGTERM]
    break_signal = getattr(signal, "SIGBREAK", None)
    if break_signal is not None:
        signals.append(break_signal)
    for signum in signals:
        try:
            loop.add_signal_handler(signum, stopping.set)
            installed.append((signum, None, True))
        except (NotImplementedError, RuntimeError):
            previous: SignalHandler = signal.getsignal(signum)
            signal.signal(signum, lambda _signal, _frame: loop.call_soon_threadsafe(stopping.set))
            installed.append((signum, previous, False))
    try:
        await _serve_until_stopped(app, stopping, output)
    finally:
        for signum, previous, loop_handler in installed:
            if loop_handler:
                loop.remove_signal_handler(signum)
            else:
                signal.signal(signum, previous)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    options = ServerOptions(
        workspace=args.workspace,
        database=args.database,
        provider=args.provider,
        host=args.host,
        port=args.port,
    )
    try:
        asyncio.run(_run_server(options, sys.stdout))
    except KeyboardInterrupt:
        return EXIT_CANCELLED
    except Exception as error:
        sys.stderr.write(f"Server startup or shutdown failed: {type(error).__name__}.\n")
        return EXIT_FAILURE
    return EXIT_SUCCESS


class _FakeReadModel:
    """Deterministic fake that exercises the read tool in the public smoke path."""

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        del config
        last_user_index = max(
            (index for index, message in enumerate(messages) if isinstance(message, HumanMessage)),
            default=-1,
        )
        turn_messages = messages[last_user_index + 1 :]
        tool_result = next(
            (message for message in reversed(turn_messages) if isinstance(message, ToolMessage)),
            None,
        )
        if tool_result is not None:
            return AIMessage(content=f"Fake summary: {tool_result.content}")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read",
                    "args": {"path": "probe.txt"},
                    "id": f"fake-read-{len(messages)}",
                    "type": "tool_call",
                }
            ],
        )


if __name__ == "__main__":
    raise SystemExit(main())
