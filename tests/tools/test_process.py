"""Acceptance tests for the structured controlled-process boundary."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from pi_agent.tools.process import (
    ProcessArguments,
    ProcessExecutionError,
    ProcessResult,
    run_controlled_process,
)


def _python_args(*code: str, timeout_seconds: float = 2) -> ProcessArguments:
    return ProcessArguments(
        executable=sys.executable,
        argv=["-c", *code],
        timeout_seconds=timeout_seconds,
    )


def test_process_arguments_are_structured_and_strict() -> None:
    args = _python_args("print('ok')")

    assert args.executable == sys.executable
    assert args.argv == ["-c", "print('ok')"]
    with pytest.raises(ValidationError):
        ProcessArguments.model_validate(
            {
                "executable": sys.executable,
                "argv": [],
                "timeout_seconds": 2,
                "shell": True,
            }
        )


def test_process_result_is_json_serializable() -> None:
    result = ProcessResult(returncode=0, stdout="ok\n", stderr="")

    assert json.loads(result.model_dump_json()) == {
        "returncode": 0,
        "stdout": "ok\n",
        "stderr": "",
        "timed_out": False,
    }


def test_disallowed_executable_is_rejected_before_spawn(tmp_path: Path) -> None:
    args = _python_args("print('must not run')")

    with pytest.raises(ProcessExecutionError, match="allowed"):
        run_controlled_process(
            args,
            allowed_executables=frozenset(),
            cwd=str(tmp_path),
        )


def test_allowed_argv_process_captures_output_without_shell(tmp_path: Path) -> None:
    args = _python_args("import sys; print(sys.argv[1])", "literal;not-a-command")

    result = run_controlled_process(
        args,
        allowed_executables=frozenset({sys.executable}),
        cwd=str(tmp_path),
    )

    assert result.returncode == 0
    assert result.stdout == "literal;not-a-command\n"
    assert result.stderr == ""
    assert result.timed_out is False


def test_timeout_is_reported(tmp_path: Path) -> None:
    args = _python_args("import time; time.sleep(10)", timeout_seconds=0.05)

    with pytest.raises(ProcessExecutionError, match="timed out"):
        run_controlled_process(
            args,
            allowed_executables=frozenset({sys.executable}),
            cwd=str(tmp_path),
        )
