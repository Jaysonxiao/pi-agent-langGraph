"""Real local process ownership, graceful control and suspended-service recovery."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from pi_agent.web import lifecycle
from pi_agent.web.app import main


def test_managed_start_pause_stop_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "service.sqlite"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    arguments = [
        sys.executable,
        "-m",
        "pi_agent.web.app",
        "--workspace",
        str(workspace),
        "--database",
        str(database),
        "--provider",
        "fake",
        "--port",
        str(port),
    ]
    with (tmp_path / "service.log").open("w") as output:
        child = subprocess.Popen(arguments, stdout=output, stderr=output)
        replacement: subprocess.Popen[str] | None = None
        try:
            wait_healthy(database, child)
            initial = lifecycle.read_instance(database)
            assert initial is not None
            assert lifecycle.request_control({**initial, "token": "wrong"}) is False
            public_status = lifecycle.status(database)
            assert "token" not in public_status
            assert initial["token"] not in json.dumps(public_status)
            if sys.platform != "win32":
                os.kill(child.pid, signal.SIGSTOP)
                deadline = time.monotonic() + 3
                while not lifecycle.paused(child.pid) and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert lifecycle.status(database)["state"] == "paused"
            lifecycle.stop_service(database)
            child.wait(timeout=5)
            assert lifecycle.status(database)["state"] == "stopped"
            assert database.exists()
            lifecycle.stop_service(database)  # Repeated stop is harmless.
            replacement = subprocess.Popen(
                [*arguments[:3], "restart", *arguments[3:]], stdout=output, stderr=output, text=True
            )
            wait_healthy(database, replacement)
            current = lifecycle.read_instance(database)
            assert current is not None and current["instance_id"] != initial["instance_id"]
            lifecycle.stop_service(database)
            replacement.wait(timeout=5)
        finally:
            for process in (child, replacement):
                if process is not None and process.poll() is None:
                    if sys.platform != "win32":
                        os.kill(process.pid, signal.SIGCONT)
                    process.terminate()
                    process.wait(timeout=10)


def wait_healthy(database: Path, process: subprocess.Popen[str] | subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        assert process.poll() is None, "Service exited before startup"
        if lifecycle.status(database)["state"] == "healthy":
            return
        time.sleep(0.05)
    raise AssertionError("Service never became healthy")


def test_foreign_lock_and_identity_mismatch_are_not_stopped(tmp_path: Path) -> None:
    from filelock import FileLock

    database = tmp_path / "service.sqlite"
    instance = lifecycle.new_instance(database, 8766)
    instance["process_identity"] = "different-start"
    lifecycle.publish(database, instance)
    with FileLock(str(database) + ".web.lock"):
        assert lifecycle.status(database)["state"] == "occupied"
        with pytest.raises(ValueError, match="unmanaged"):
            lifecycle.stop_service(database, force=True)
    assert lifecycle.status(database)["state"] == "stale"


def test_cli_reports_port_conflict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        assert main(["--port", str(port), "--database", str(tmp_path / "db")]) == 1
        assert "端口" in capsys.readouterr().err
