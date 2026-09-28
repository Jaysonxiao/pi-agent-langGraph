"""Public server app starts, serves a fake tool turn, and preserves SQLite state."""

import asyncio
from pathlib import Path
from typing import cast

import pytest

from pi_agent.client.client import RemoteClient
from pi_agent.client.transport import connect_tcp
from pi_agent.server.app import ServerApplication, ServerOptions, create_server_application
from pi_agent.server.dispatcher import ServerDispatcher


def test_server_app_serves_fake_read_and_reopens_session_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "probe.txt").write_text("probe is ready", encoding="utf-8")
    database = tmp_path / "sessions.sqlite"
    monkeypatch.setenv("PI_AGENT_REMOTE_TOKEN", "m108-test-token")
    options = ServerOptions(workspace=workspace, database=database, provider="fake", port=0)

    async def scenario() -> None:
        first_server = create_server_application(options)
        port = await first_server.start()
        first_client = RemoteClient(lambda: connect_tcp(port))
        await first_client.connect()
        created = await first_client.create_session()
        first_turn = await first_client.prompt(created.session_id, "Read probe.txt and summarize")
        assert first_turn.session_id == created.session_id
        assert any("probe is ready" in message.text for message in first_turn.messages)
        await first_client.close()
        await first_server.close()

        second_server = create_server_application(
            ServerOptions(
                workspace=workspace,
                database=database,
                provider="fake",
                port=port,
            )
        )
        await second_server.start()
        second_client = RemoteClient(lambda: connect_tcp(port))
        await second_client.connect()
        reopened = await second_client.get_snapshot(created.session_id)
        assert reopened.session_id == created.session_id
        assert any("Fake summary:" in message.text for message in reopened.messages)
        second_turn = await second_client.prompt(created.session_id, "Continue")
        assert sum(message.role == "assistant" for message in second_turn.messages) >= 2
        await second_client.close()
        await second_server.close()

    asyncio.run(scenario())


def test_server_application_close_releases_injected_model_once(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls = 0

    async def close_model() -> None:
        nonlocal calls
        calls += 1

    app = ServerApplication(
        options=ServerOptions(workspace=workspace, database=tmp_path / "db.sqlite"),
        dispatcher=cast(ServerDispatcher, object()),
        server_epoch="epoch-1",
        close_model=close_model,
    )

    async def scenario() -> None:
        await app.close()
        await app.close()

    asyncio.run(scenario())
    assert calls == 1
