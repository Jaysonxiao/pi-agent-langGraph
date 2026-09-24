"""Red tests for learner-owned M8.7-R6 controlled async process spawning."""

import asyncio
from pathlib import Path

import pytest

from pi_agent.tools.async_process import AsyncioSpawnedProcess, spawn_controlled_process
from pi_agent.tools.process import ProcessArguments, ProcessExecutionError


class RawProcess:
    """Byte-oriented asyncio Process double with observable termination."""

    def __init__(self, stdout: bytes = b"ok", stderr: bytes = b"") -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.terminated = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return (self._stdout, self._stderr)

    def terminate(self) -> None:
        self.terminated = True


def test_disallowed_executable_is_rejected_before_async_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def unexpected_spawn(*_: object, **__: object) -> RawProcess:
        raise AssertionError("disallowed executable must not spawn")

    monkeypatch.setattr(
        "pi_agent.tools.async_process.asyncio.create_subprocess_exec",
        unexpected_spawn,
    )

    with pytest.raises(ProcessExecutionError) as raised:
        asyncio.run(
            spawn_controlled_process(
                _args("blocked"),
                allowed_executables=frozenset({"allowed"}),
                cwd=str(tmp_path),
            )
        )

    assert raised.value.code == "executable_not_allowed"


def test_invalid_cwd_is_rejected_before_async_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unexpected_spawn(*_: object, **__: object) -> RawProcess:
        raise AssertionError("invalid cwd must not spawn")

    monkeypatch.setattr(
        "pi_agent.tools.async_process.asyncio.create_subprocess_exec",
        unexpected_spawn,
    )

    with pytest.raises(ProcessExecutionError) as raised:
        asyncio.run(
            spawn_controlled_process(
                _args("allowed"),
                allowed_executables=frozenset({"allowed"}),
                cwd="missing-directory",
            )
        )

    assert raised.value.code == "execution_failed"


def test_async_spawn_uses_structured_argv_pipes_and_utf8_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    raw = RawProcess(stdout=b"ok\xff", stderr=b"warn")

    async def fake_spawn(*argv: str, **kwargs: object) -> RawProcess:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return raw

    monkeypatch.setattr(
        "pi_agent.tools.async_process.asyncio.create_subprocess_exec",
        fake_spawn,
    )

    spawned = asyncio.run(
        spawn_controlled_process(
            _args("allowed", "--flag", "value"),
            allowed_executables=frozenset({"allowed"}),
            cwd=str(tmp_path),
        )
    )

    assert isinstance(spawned, AsyncioSpawnedProcess)
    assert captured["argv"] == ("allowed", "--flag", "value")
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["stdin"] is asyncio.subprocess.DEVNULL
    assert kwargs["stdout"] is asyncio.subprocess.PIPE
    assert kwargs["stderr"] is asyncio.subprocess.PIPE
    assert asyncio.run(spawned.communicate()) == ("ok�", "warn")


def test_async_spawn_maps_os_error_to_stable_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def failing_spawn(*_: object, **__: object) -> RawProcess:
        raise OSError("synthetic spawn failure")

    monkeypatch.setattr(
        "pi_agent.tools.async_process.asyncio.create_subprocess_exec",
        failing_spawn,
    )

    with pytest.raises(ProcessExecutionError) as raised:
        asyncio.run(
            spawn_controlled_process(
                _args("allowed"),
                allowed_executables=frozenset({"allowed"}),
                cwd=str(tmp_path),
            )
        )

    assert raised.value.code == "execution_failed"


def _args(executable: str, *argv: str) -> ProcessArguments:
    return ProcessArguments(executable=executable, argv=list(argv), timeout_seconds=1)
