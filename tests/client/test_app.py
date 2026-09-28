"""Public client CLI parsing, command routing, and cleanup contract."""

import argparse
import asyncio
import io
from typing import cast

import pytest

from pi_agent.client.app import build_parser, dispatch_command, run_cli
from pi_agent.client.client import RemoteClient
from pi_agent.protocol.messages import DisplayMessage, SessionSnapshot


def _snapshot() -> SessionSnapshot:
    return SessionSnapshot(
        session_id="session-1",
        server_epoch="epoch-1",
        revision=3,
        checkpoint_id="checkpoint-3",
        graph_status="idle",
        run_phase="idle",
        run_outcome="completed",
        active_run_id=None,
        message_count=1,
        messages=(DisplayMessage(message_id="message-1", role="assistant", text="ready"),),
        truncated=False,
    )


class _RemoteClientSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.snapshot = _snapshot()
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True

    async def create_session(self) -> SessionSnapshot:
        self.calls.append(("create",))
        return self.snapshot

    async def get_snapshot(self, session_id: str) -> SessionSnapshot:
        self.calls.append(("snapshot", session_id))
        return self.snapshot

    async def prompt(self, session_id: str, text: str) -> SessionSnapshot:
        self.calls.append(("prompt", session_id, text))
        return self.snapshot

    async def cancel(self, session_id: str, run_id: str) -> SessionSnapshot:
        self.calls.append(("cancel", session_id, run_id))
        return self.snapshot


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["create"], ("create",)),
        (["snapshot", "--session-id", "session-2"], ("snapshot", "session-2")),
        (
            ["prompt", "--session-id", "session-2", "--text", "read probe"],
            ("prompt", "session-2", "read probe"),
        ),
        (
            ["cancel", "--session-id", "session-2", "--run-id", "run-4"],
            ("cancel", "session-2", "run-4"),
        ),
    ],
)
def test_dispatches_each_public_command_to_matching_remote_api(
    argv: list[str], expected: tuple[object, ...]
) -> None:
    async def scenario() -> None:
        args = build_parser().parse_args(["--port", "8765", *argv])
        client = _RemoteClientSpy()
        result = await dispatch_command(cast(RemoteClient, client), args)
        assert result == client.snapshot
        assert client.calls == [expected]

    asyncio.run(scenario())


def test_run_cli_closes_client_when_dispatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        args = build_parser().parse_args(["--port", "8765", "create"])
        client = _RemoteClientSpy()

        def factory(_host: str, _port: int) -> RemoteClient:
            return cast(RemoteClient, client)

        async def fail_dispatch(
            _client: RemoteClient, _args: argparse.Namespace
        ) -> SessionSnapshot:
            raise RuntimeError("dispatch failure")

        monkeypatch.setattr("pi_agent.client.app.dispatch_command", fail_dispatch)
        with pytest.raises(RuntimeError, match="dispatch failure"):
            await run_cli(args, io.StringIO(), client_factory=factory)
        assert client.connected
        assert client.closed

    asyncio.run(scenario())
