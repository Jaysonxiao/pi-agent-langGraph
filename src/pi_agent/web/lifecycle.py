"""Local service ownership and authenticated control, independent of the browser cookie."""

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from filelock import FileLock, Timeout


def record_path(database: Path) -> Path:
    return Path(str(database) + ".web.instance.json")


def process_identity(pid: int) -> str | None:
    """Use OS start identity, never the mere existence of a PID."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                return None
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat=,lstart="], capture_output=True, text=True, check=False
    )
    parts = result.stdout.strip().split(maxsplit=1)
    return parts[1] if len(parts) == 2 and not parts[0].startswith("Z") else None


def paused(pid: int) -> bool:
    if sys.platform == "win32":
        return False
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, check=False
    )
    return result.stdout.strip().startswith("T")


def new_instance(database: Path, port: int) -> dict[str, Any]:
    identity = process_identity(os.getpid())
    if identity is None:
        raise ValueError("Cannot establish service process identity.")
    return {
        "pid": os.getpid(),
        "process_identity": identity,
        "database": str(database),
        "port": port,
        "instance_id": secrets.token_hex(16),
        "token": secrets.token_urlsafe(32),
    }


def publish(database: Path, instance: dict[str, Any]) -> None:
    target = record_path(database)
    temporary = target.with_suffix(".tmp")
    # The OS lease is held before publishing, so another instance cannot overwrite it.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(instance, output)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def read_instance(database: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(record_path(database).read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("database") != str(database)
            or type(value.get("pid")) is not int
            or value["pid"] <= 0
            or type(value.get("port")) is not int
            or not 1 <= value["port"] <= 65535
            or not all(
                isinstance(value.get(key), str) and value[key]
                for key in ("token", "instance_id", "process_identity")
            )
        ):
            return None
        return value
    except (OSError, ValueError):
        return None


def owns_process(instance: dict[str, Any]) -> bool:
    return bool(process_identity(instance["pid"]) == instance["process_identity"])


def request_control(instance: dict[str, Any], *, stop: bool = False) -> bool:
    try:
        with httpx.Client(trust_env=False, timeout=1) as client:
            response = client.request(
                "POST" if stop else "GET",
                f"http://127.0.0.1:{instance['port']}/_pi/service",
                headers={"x-pi-service-token": instance["token"]},
            )
        return (
            response.status_code == 200
            and response.json().get("instance_id") == instance["instance_id"]
        )
    except (httpx.HTTPError, ValueError):
        return False


def locked(database: Path) -> bool:
    if not database.parent.exists():
        return False
    lease = FileLock(str(database) + ".web.lock", timeout=0)
    try:
        with lease:
            return False
    except Timeout:
        return True


def status(database: Path) -> dict[str, Any]:
    instance = read_instance(database)
    state = "stopped"
    if instance is not None and owns_process(instance) and locked(database):
        state = (
            "paused"
            if paused(instance["pid"])
            else ("healthy" if request_control(instance) else "unresponsive")
        )
    elif locked(database):
        state = "occupied"
    elif instance is not None:
        state = "stale"
    result: dict[str, Any] = {"state": state, "database": str(database)}
    if instance is not None:
        result.update(pid=instance["pid"], address=f"http://127.0.0.1:{instance['port']}")
    return result


def stop_service(database: Path, *, force: bool = False, timeout: float = 10) -> None:
    instance = read_instance(database)
    if not locked(database):
        return
    if instance is None or not owns_process(instance):
        raise ValueError("Database is occupied by an unmanaged service; stop it in its terminal.")
    if sys.platform != "win32" and paused(instance["pid"]) and owns_process(instance):
        os.kill(instance["pid"], signal.SIGCONT)
    accepted = request_control(instance, stop=True)
    if not accepted and not force:
        raise ValueError("Service did not accept shutdown; inspect it or use --force explicitly.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not owns_process(instance) and not locked(database):
            return
        time.sleep(0.1)
    if force and owns_process(instance):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(instance["pid"]), "/T", "/F"], check=True)
        else:
            os.kill(instance["pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not owns_process(instance) and not locked(database):
                return
            time.sleep(0.1)
    raise ValueError(
        "Service has not released its process and database; restart was not attempted."
    )
