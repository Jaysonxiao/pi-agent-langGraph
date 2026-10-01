"""Exercise the real platform launcher with an isolated workspace and database."""

import http.cookiejar
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import cast


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="pi web smoke ") as directory:
        temporary = Path(directory)
        workspace = temporary / "workspace with spaces"
        workspace.mkdir()
        (workspace / "probe.txt").write_text("PI-WEB-STARTUP-SMOKE", encoding="utf-8")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        if sys.platform == "win32":
            arguments = [
                "powershell",
                "-NoProfile",
                "-File",
                str(root / "scripts/start-web.ps1"),
                "-Workspace",
                str(workspace),
                "-Database",
                str(temporary / "web.sqlite"),
                "-Port",
                str(port),
            ]
            flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            arguments = [
                "bash",
                str(root / "scripts/start-web.sh"),
                "--workspace",
                str(workspace),
                "--database",
                str(temporary / "web.sqlite"),
                "--port",
                str(port),
            ]
            flags = 0
        base_url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

        def request(path: str, payload: dict[str, str] | None = None) -> dict[str, object]:
            body = json.dumps(payload).encode() if payload is not None else None
            req = urllib.request.Request(
                base_url + path,
                data=body,
                headers={"X-Pi-Request": "1", "Content-Type": "application/json"},
                method="POST" if payload is not None else "GET",
            )
            with opener.open(req, timeout=2) as response:
                return cast(dict[str, object], json.load(response))

        with (temporary / "service.log").open("w+") as log:
            process = subprocess.Popen(
                arguments,
                cwd=temporary,
                stdout=log,
                stderr=log,
                creationflags=flags,
                start_new_session=sys.platform != "win32",
            )
            try:
                deadline = time.monotonic() + 180
                while True:
                    if process.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(f"Launcher exited before readiness:\n{log.read()}")
                    try:
                        config = request("/api/bootstrap")
                        break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                "Launcher did not become ready within 180 seconds."
                            ) from None
                        time.sleep(0.1)
                assert config["provider"] == "fake"
                assert config["capabilities"] == [
                    "read",
                    "list",
                    "search",
                    "write",
                    "edit",
                    "propose_command",
                ]
                assert config["require_approval"] is True
                assert config["allowed_executables"]
                created = request("/api/sessions", {})
                sid = str(created["session_id"])
                run = request(
                    f"/api/sessions/{sid}/runs",
                    {
                        "text": "读取 probe.txt",
                        "request_id": "startup-smoke-request",
                    },
                )
                deadline = time.monotonic() + 15
                while request(f"/api/runs/{run['run_id']}")["status"] == "running":
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Fake read request did not finish.")
                    time.sleep(0.05)
                assert request(f"/api/runs/{run['run_id']}")["status"] == "completed"
                view = request(f"/api/sessions/{sid}")
                assert "PI-WEB-STARTUP-SMOKE" in json.dumps(view["history"])
                print("PASS: launcher install/build, HTTP bootstrap, real read, and persistence")
            finally:
                if process.poll() is None:
                    if sys.platform == "win32":
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        if sys.platform == "win32":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True
                            )
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
                # uv propagates SIGTERM as 128+15; Windows console signals use NTSTATUS.
                expected = (0, 130, 143, -signal.SIGTERM, -1073741510)
                assert process.returncode in expected, process.returncode


if __name__ == "__main__":
    main()
