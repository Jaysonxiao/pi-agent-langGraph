"""Red tests for learner-owned M8.7-R9 process-tree termination policy."""

import asyncio
import signal

import pytest

from pi_agent.tools.async_process import terminate_async_process_tree


class ProcessIdentity:
    def __init__(self, *, pid: int = 321, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode


class TaskkillProcess:
    def __init__(self) -> None:
        self.waited = False

    async def wait(self) -> int:
        self.waited = True
        return 0


def test_exited_process_tree_is_not_terminated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected(*_: object, **__: object) -> TaskkillProcess:
        raise AssertionError("exited process must not invoke taskkill")

    monkeypatch.setattr("pi_agent.tools.async_process.asyncio.create_subprocess_exec", unexpected)

    asyncio.run(terminate_async_process_tree(ProcessIdentity(returncode=0), platform="win32"))


def test_windows_uses_taskkill_tree_and_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    taskkill = TaskkillProcess()

    async def spawn(*argv: str, **kwargs: object) -> TaskkillProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return taskkill

    monkeypatch.setattr("pi_agent.tools.async_process.asyncio.create_subprocess_exec", spawn)

    asyncio.run(terminate_async_process_tree(ProcessIdentity(pid=777), platform="win32"))

    assert captured["argv"] == ("taskkill", "/F", "/T", "/PID", "777")
    assert taskkill.waited


def test_posix_uses_process_group_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "pi_agent.tools.async_process._kill_process_group",
        lambda pid, sig: calls.append((pid, sig)),
    )

    asyncio.run(terminate_async_process_tree(ProcessIdentity(pid=888), platform="linux"))

    assert calls == [(888, signal.SIGTERM)]


def test_missing_posix_process_tree_is_already_terminated(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_: int, __: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr("pi_agent.tools.async_process._kill_process_group", missing)

    asyncio.run(terminate_async_process_tree(ProcessIdentity(), platform="linux"))
