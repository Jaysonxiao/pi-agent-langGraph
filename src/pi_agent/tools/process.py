"""Structured, allowlisted subprocess boundary (M4 learner slice)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pi_agent.tools.output import TextOutputBudget

ProcessErrorCode = Literal["executable_not_allowed", "timeout", "execution_failed"]

# 进程输出会回灌给模型, 必须复用只读工具同一套行数/字节上限.
_PROCESS_OUTPUT_BUDGET = TextOutputBudget()

# 超时后给进程树一次短暂的收尸窗口, 避免管道泄漏.
_REAP_TIMEOUT_SECONDS = 2.0


class ProcessExecutionError(RuntimeError):
    """Stable error raised by the controlled process boundary."""

    def __init__(self, code: ProcessErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProcessArguments(BaseModel):
    """Model-visible structured argv; no shell command string is accepted."""

    model_config = ConfigDict(extra="forbid")

    executable: str
    argv: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(gt=0, le=30)


class ProcessResult(BaseModel):
    """Bounded process result returned to the tool layer."""

    model_config = ConfigDict(extra="forbid")

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate the spawned process and any children it created."""
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        # /T 会连同子进程一起结束, 避免 timeout 后留下悬挂任务.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return


def _bound_stream(text: str | None) -> str:
    """Keep one captured stream within the shared model-visible budget."""
    return _PROCESS_OUTPUT_BUDGET.apply(text or "").render()


def run_controlled_process(
    args: ProcessArguments,
    *,
    allowed_executables: frozenset[str],
    cwd: str,
) -> ProcessResult:
    """Run one allowlisted argv command without a shell."""

    # 精确匹配 allowlist, 拒绝路径别名或未授权解释器, 且必须发生在 spawn 之前.
    if args.executable not in allowed_executables:
        raise ProcessExecutionError(
            "executable_not_allowed",
            f"Executable is not allowed: {args.executable}",
        )

    # cwd 由应用层传入工作区根; 这里只确认它当前是可用目录, 不接受任意路径字符串.
    if not Path(cwd).is_dir():
        raise ProcessExecutionError(
            "execution_failed",
            f"Working directory is not usable: {cwd}",
        )

    popen_kwargs: dict[str, object] = {
        "args": [args.executable, *args.argv],
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        # 新进程组便于 taskkill /T 回收整棵树; 不创建可见控制台窗口.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        popen_kwargs["creationflags"] = creationflags | create_no_window
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(**popen_kwargs)  # type: ignore[call-overload]
    except OSError as exc:
        raise ProcessExecutionError(
            "execution_failed",
            f"Failed to execute process: {exc}",
        ) from exc

    try:
        stdout, stderr = proc.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(proc)
        try:
            proc.communicate(timeout=_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        raise ProcessExecutionError(
            "timeout",
            f"Process timed out after {args.timeout_seconds} seconds.",
        ) from None
    except Exception as exc:
        _terminate_process_tree(proc)
        raise ProcessExecutionError(
            "execution_failed",
            f"Failed to execute process: {exc}",
        ) from exc

    returncode = proc.returncode
    if returncode is None:
        raise ProcessExecutionError(
            "execution_failed",
            "Process finished without a return code.",
        )

    # 非零退出是命令结果, 不是策略错误; 仍返回有界 stdout/stderr.
    return ProcessResult(
        returncode=returncode,
        stdout=_bound_stream(stdout),
        stderr=_bound_stream(stderr),
        timed_out=False,
    )
