"""Run the same client/server contract over memory and localhost TCP transports."""

import asyncio
from pathlib import Path
from typing import Literal, cast

from pi_agent.client.client import RemoteClient
from pi_agent.client.transport import connect_tcp
from pi_agent.protocol.messages import DisplayMessage, SessionSnapshot
from pi_agent.protocol.transport import AsyncByteConnection
from pi_agent.runtime.session import SessionRuntimeConfig
from pi_agent.server.connection import ServerConnection
from pi_agent.server.dispatcher import ServerCommandService, ServerDispatcher
from pi_agent.server.sessions import SessionCoordinator
from pi_agent.server.transports.tcp import TcpByteServer
from pi_agent.sessions.metadata import SessionRecord

TEST_TOKEN = "m108-conformance-token"


class _MemoryConnection:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self.peer: _MemoryConnection | None = None
        self.closed = False

    async def read(self, max_bytes: int) -> bytes:
        del max_bytes
        return await self.incoming.get()

    async def send(self, data: bytes) -> None:
        if self.closed or self.peer is None or self.peer.closed:
            raise ConnectionError("memory transport is closed")
        self.peer.incoming.put_nowait(data)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.incoming.put_nowait(b"")
        if self.peer is not None and not self.peer.closed:
            self.peer.incoming.put_nowait(b"")


class _Catalog:
    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}

    def record_session(self, session_id: str) -> SessionRecord:
        record = SessionRecord(session_id, "created", "updated")
        self.records[session_id] = record
        return record

    def list_sessions(self) -> list[SessionRecord]:
        return list(self.records.values())


class _Runtime:
    def __init__(self) -> None:
        self.turns: dict[str, list[str]] = {}

    async def prompt(
        self, config: SessionRuntimeConfig, *, content: str, message_id: str
    ) -> object:
        del message_id
        self.turns.setdefault(config.session_id, []).append(content)
        return {"status": "completed"}

    async def snapshot(
        self,
        config: SessionRuntimeConfig,
        *,
        revision: int,
        run_phase: str = "idle",
        run_outcome: str | None = None,
        active_run_id: str | None = None,
    ) -> SessionSnapshot:
        turns = self.turns.get(config.session_id, [])
        messages = tuple(
            DisplayMessage(message_id=f"m-{index}", role="assistant", text=text)
            for index, text in enumerate(turns)
        )
        return SessionSnapshot(
            session_id=config.session_id,
            server_epoch="conformance-epoch",
            revision=revision,
            checkpoint_id=None,
            graph_status="idle",
            run_phase=cast(Literal["idle", "running", "cancelling", "needs_recovery"], run_phase),
            run_outcome=cast(Literal["completed", "failed", "cancelled"] | None, run_outcome),
            active_run_id=active_run_id,
            message_count=len(messages),
            messages=messages,
            truncated=False,
        )


def _dispatcher(workspace: Path, database: Path) -> ServerDispatcher:
    return ServerDispatcher(
        ServerCommandService(
            runtime=_Runtime(),
            catalog=_Catalog(),
            coordinator=SessionCoordinator(),
            database=database,
            workspace=workspace,
            id_factory=iter(("session-1", "run-1", "message-1", "run-2", "message-2")).__next__,
        )
    )


async def _exercise(client: RemoteClient) -> None:
    await client.connect()
    created = await client.create_session()
    assert created.session_id == "session-1"
    first = await client.prompt(created.session_id, "Read probe.txt")
    assert first.messages[-1].text == "Read probe.txt"
    queried = await client.get_snapshot(created.session_id)
    assert queried.revision == first.revision
    assert queried.message_count == 1
    await client.close()


def test_memory_and_tcp_transports_share_request_conformance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        client_side = _MemoryConnection()
        server_side = _MemoryConnection()
        client_side.peer = server_side
        server_side.peer = client_side
        dispatcher = _dispatcher(workspace, tmp_path / "memory.sqlite")
        memory_handler = ServerConnection(server_side, dispatcher, server_epoch="conformance-epoch")
        memory_task = asyncio.create_task(memory_handler.serve())

        async def memory_factory() -> AsyncByteConnection:
            return client_side

        await _exercise(RemoteClient(memory_factory))
        await memory_task

        tcp_dispatcher = _dispatcher(workspace, tmp_path / "tcp.sqlite")

        async def tcp_handler(connection: AsyncByteConnection) -> None:
            await ServerConnection(
                connection, tcp_dispatcher, server_epoch="conformance-epoch"
            ).serve()

        server = await TcpByteServer.start(tcp_handler, token=TEST_TOKEN, port=0)
        try:

            async def tcp_factory() -> AsyncByteConnection:
                return await connect_tcp(server.port, token=TEST_TOKEN)

            await _exercise(RemoteClient(tcp_factory))
        finally:
            await server.close()

    asyncio.run(scenario())
