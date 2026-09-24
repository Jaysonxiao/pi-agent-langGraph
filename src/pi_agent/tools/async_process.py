"""Cancellation-safe lifetime management for an already spawned process."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Protocol, cast

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.runner import run_cancellable
from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.output import TextOutputBudget
from pi_agent.tools.process import ProcessArguments, ProcessExecutionError, ProcessResult


class AsyncSpawnedProcess(Protocol):
    """Small process port whose external resource needs explicit reaping."""

    async def communicate(self) -> tuple[str, str]:
        """Wait for process completion and collect its output."""
        ...

    async def terminate_tree(self) -> None:
        """Request termination of the process and every child it spawned."""
        ...


class AsyncTreeProcess(Protocol):
    """Minimum process identity needed by the platform tree terminator."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...


async def terminate_async_process_tree(
    process: AsyncTreeProcess,
    *,
    platform: str,
) -> None:
    """Request termination of a live process tree without reaping it."""
    # 已经退出则不重复发终止; 最终 reap 仍由 R5 communicate 负责.
    if process.returncode is not None:
        return
    if platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/F",
            "/T",
            "/PID",
            str(process.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if await killer.wait() != 0:
            raise OSError("Process-tree termination was denied by the host.")
        return
    try:
        _kill_process_group(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _kill_process_group(pid: int, sig: int) -> None:
    """Call POSIX killpg through a seam that remains importable on Windows."""
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        raise OSError("Process-group signalling is unavailable on this platform.")
    killpg(pid, sig)


class AsyncioSpawnedProcess:
    """Adapter for asyncio's byte-oriented subprocess process."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @property
    def returncode(self) -> int | None:
        return getattr(self._process, "returncode", None)

    async def communicate(self) -> tuple[str, str]:
        """Collect bytes and decode them deterministically for the tool layer."""
        if (
            getattr(self._process, "stdout", None) is None
            or getattr(self._process, "stderr", None) is None
        ):
            stdout, stderr = await self._process.communicate()
            return (_decode_stream(stdout), _decode_stream(stderr))
        stdout_reader = cast(asyncio.StreamReader, self._process.stdout)
        stderr_reader = cast(asyncio.StreamReader, self._process.stderr)
        collected = await asyncio.gather(
            asyncio.create_task(_collect_bounded(stdout_reader)),
            asyncio.create_task(_collect_bounded(stderr_reader)),
        )
        await self._process.wait()
        return (collected[0], collected[1])

    async def terminate_tree(self) -> None:
        """Delegate to the platform tree policy instead of the direct child only."""
        try:
            await terminate_async_process_tree(self._process, platform=sys.platform)
        except OSError as exc:
            # Failure to kill descendants must never masquerade as a successful
            # timeout. Reap the direct child and release our pipe handles.
            with suppress(ProcessLookupError, PermissionError):
                self._process.kill()
            for stream in (self._process.stdout, self._process.stderr):
                transport = getattr(stream, "_transport", None)
                if transport is not None:
                    transport.close()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._process.wait(), timeout=2)
            raise ProcessExecutionError(
                "execution_failed", "Process tree could not be terminated under host permissions."
            ) from exc
        if sys.platform != "win32" and self._process.returncode is None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    _kill_process_group(self._process.pid, signal.SIGKILL)


async def spawn_controlled_process(
    args: ProcessArguments,
    *,
    allowed_executables: frozenset[str],
    cwd: str,
    workspace: WorkspacePathPolicy | None = None,
) -> AsyncSpawnedProcess:
    """Validate and spawn one allowlisted argv command without a shell."""
    # 精确匹配 allowlist 与可用工作目录, 必须发生在 create_subprocess_exec 之前.
    if args.executable not in allowed_executables:
        raise ProcessExecutionError(
            "executable_not_allowed",
            f"Executable is not allowed: {args.executable}",
        )
    if not Path(cwd).is_dir():
        raise ProcessExecutionError(
            "execution_failed",
            f"Working directory is not usable: {cwd}",
        )

    if workspace is not None:
        try:
            authorized_cwd = workspace.resolve(cwd)
        except ValueError as exc:
            raise ProcessExecutionError(
                "execution_failed", "Working directory is outside the approved workspace."
            ) from exc
        if not authorized_cwd.is_dir():
            raise ProcessExecutionError(
                "execution_failed", "Working directory must be a directory."
            )

    platform_kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        platform_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    else:
        platform_kwargs["start_new_session"] = True

    try:
        process = await asyncio.create_subprocess_exec(
            args.executable,
            *args.argv,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **platform_kwargs,  # type: ignore[arg-type]
        )
    except OSError as exc:
        raise ProcessExecutionError(
            "execution_failed",
            f"Failed to execute process: {exc}",
        ) from exc
    return AsyncioSpawnedProcess(process)


async def _collect_bounded(reader: asyncio.StreamReader, limit: int = 64 * 1024) -> str:
    """Drain pipes without retaining more than a fixed head in memory."""
    retained = bytearray()
    truncated = False
    while chunk := await reader.read(16 * 1024):
        available = limit - len(retained)
        if available > 0:
            retained.extend(chunk[:available])
        truncated |= len(chunk) > available
    rendered = retained.decode("utf-8", errors="replace")
    return f"{rendered}\n... [capture truncated]" if truncated else rendered


def _decode_stream(data: bytes | str | None) -> str:
    """Decode subprocess bytes as UTF-8; invalid sequences become replacement chars."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


async def run_spawned_process(
    spawn: Callable[[], Awaitable[AsyncSpawnedProcess]],
    token: AsyncCancellationToken,
    /,
) -> tuple[str, str]:
    """Spawn once, then terminate and reap it whenever cancellation wins."""

    async def operation() -> tuple[str, str]:
        # Python task/token 由 runner 拥有; 这里只管理外部进程资源.
        process = await spawn()
        try:
            return await process.communicate()
        except asyncio.CancelledError:
            # 先结束整棵进程树, 等它真正停下来后才做最终 reap.
            await process.terminate_tree()
            await process.communicate()
            raise

    return await run_cancellable(operation, token)


async def run_controlled_async_process(
    args: ProcessArguments,
    *,
    allowed_executables: frozenset[str],
    cwd: str,
    token: AsyncCancellationToken,
    workspace: WorkspacePathPolicy | None = None,
    spawned: list[AsyncSpawnedProcess] | None = None,
) -> tuple[str, str]:
    """Run a controlled process with a distinct deadline failure boundary."""

    async def spawn() -> AsyncSpawnedProcess:
        process = await spawn_controlled_process(
            args=args,
            allowed_executables=allowed_executables,
            cwd=cwd,
            workspace=workspace,
        )
        if spawned is not None:
            spawned.append(process)
        return process

    try:
        # deadline 取消内部 await, R5 先 terminate/reap, 再把 TimeoutError 映射为策略错误.
        async with asyncio.timeout(args.timeout_seconds):
            return await run_spawned_process(spawn, token)
    except TimeoutError:
        raise ProcessExecutionError(
            "timeout",
            f"Process timed out after {args.timeout_seconds} seconds.",
        ) from None


async def run_controlled_async_process_result(
    args: ProcessArguments,
    *,
    allowed_executables: frozenset[str],
    cwd: str,
    token: AsyncCancellationToken,
    output_budget: TextOutputBudget,
    workspace: WorkspacePathPolicy | None = None,
) -> ProcessResult:
    """Return a bounded normal process result without rewriting failure paths."""
    # 不捕获 timeout/取消; 只有 R7 正常返回后才构造结果.
    spawned: list[AsyncSpawnedProcess] = []
    stdout, stderr = await run_controlled_async_process(
        args=args,
        allowed_executables=allowed_executables,
        cwd=cwd,
        token=token,
        workspace=workspace,
        spawned=spawned,
    )
    returncode = getattr(spawned[0], "returncode", 0) if spawned else 0
    if returncode is None:
        raise ProcessExecutionError("execution_failed", "Process exited without a return code.")
    return ProcessResult(
        returncode=returncode,
        stdout=_bound_stream(stdout, output_budget),
        stderr=_bound_stream(stderr, output_budget),
        timed_out=False,
    )


def _bound_stream(text: str, output_budget: TextOutputBudget) -> str:
    """Apply the shared line/byte budget; keep a short marker when truncated."""
    bounded = output_budget.apply(text)
    if not bounded.truncated:
        return bounded.render()
    # 本片不宣称真实 returncode; 截断提示保持简短, 不改写失败路径.
    if not bounded.content:
        return "... [truncated]"
    return f"{bounded.content}\n... [truncated]"
