"""Real CLI process smoke: read a fixture, restart server, and resume by session ID."""

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

TOKEN = "m108-subprocess-smoke-token"


@pytest.mark.skipif(sys.platform == "emscripten", reason="subprocesses are unavailable")
def test_public_server_and_client_processes_reopen_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "probe.txt").write_text("subprocess probe content", encoding="utf-8")
    database = tmp_path / "sessions.sqlite"
    server_module = "pi_agent.server.app"
    client_module = "pi_agent.client.app"

    async def start_server(port: int = 0) -> tuple[asyncio.subprocess.Process, int]:
        env = os.environ.copy()
        env["PI_AGENT_REMOTE_TOKEN"] = TOKEN
        if sys.platform == "win32":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            flags = 0
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            server_module,
            "--provider",
            "fake",
            "--workspace",
            str(workspace),
            "--database",
            str(database),
            "--port",
            str(port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            creationflags=flags,
        )
        assert process.stdout is not None
        line = await asyncio.wait_for(process.stdout.readline(), timeout=10)
        assert line, "server exited before publishing readiness"
        assert TOKEN.encode() not in line
        assert b"subprocess probe content" not in line
        ready = json.loads(line)
        assert ready["event"] == "ready"
        return process, int(ready["port"])

    async def run_client(port: int, *arguments: str) -> dict[str, object]:
        env = os.environ.copy()
        env["PI_AGENT_REMOTE_TOKEN"] = TOKEN
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            client_module,
            "--port",
            str(port),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        assert process.returncode == 0, stderr.decode("utf-8", errors="replace")
        assert TOKEN.encode() not in stdout + stderr
        payload: object = json.loads(stdout)
        assert isinstance(payload, dict)
        return cast(dict[str, object], payload)

    async def stop_server(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGTERM)
        await asyncio.wait_for(process.wait(), timeout=10)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        assert process.returncode in (0, 130), stderr.decode("utf-8", errors="replace")
        assert TOKEN.encode() not in stdout + stderr
        assert b"subprocess probe content" not in stdout + stderr
        assert b"Read probe.txt and summarize" not in stdout + stderr

    async def scenario() -> None:
        server, port = await start_server()
        try:
            created = await run_client(port, "create")
            session_id = str(created["session_id"])
            prompted = await run_client(
                port,
                "prompt",
                "--session-id",
                session_id,
                "--text",
                "Read probe.txt and summarize",
            )
            messages = prompted["messages"]
            assert isinstance(messages, list)
            assert any("subprocess probe content" in str(item["text"]) for item in messages)
        finally:
            await stop_server(server)

        server, restarted_port = await start_server(port)
        try:
            reopened = await run_client(restarted_port, "snapshot", "--session-id", session_id)
            assert reopened["session_id"] == session_id
            messages = reopened["messages"]
            assert isinstance(messages, list)
            assert any("Fake summary:" in str(item["text"]) for item in messages)
        finally:
            await stop_server(server)

    asyncio.run(scenario())
