"""Red tests for learner-owned M8.7-R8 normal async process result mapping."""

import asyncio

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_process import run_controlled_async_process_result
from pi_agent.tools.output import TextOutputBudget
from pi_agent.tools.process import ProcessArguments, ProcessExecutionError, ProcessResult


def test_normal_async_process_result_bounds_both_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    async def completed(**_: object) -> tuple[str, str]:
        return ("one\ntwo\nthree", "warn\none")

    monkeypatch.setattr("pi_agent.tools.async_process.run_controlled_async_process", completed)

    result = asyncio.run(_run())

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.stdout == "one\ntwo\n... [truncated]"
    assert result.stderr == "warn\none"


def test_timeout_is_not_rewritten_as_success_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def timed_out(**_: object) -> tuple[str, str]:
        raise ProcessExecutionError("timeout", "controlled timeout")

    monkeypatch.setattr("pi_agent.tools.async_process.run_controlled_async_process", timed_out)

    with pytest.raises(ProcessExecutionError) as raised:
        asyncio.run(_run())

    assert raised.value.code == "timeout"


def test_cancellation_is_not_rewritten_as_success_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancelled(**_: object) -> tuple[str, str]:
        raise asyncio.CancelledError()

    monkeypatch.setattr("pi_agent.tools.async_process.run_controlled_async_process", cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())


async def _run() -> ProcessResult:
    return await run_controlled_async_process_result(
        ProcessArguments(executable="allowed", argv=[], timeout_seconds=1),
        allowed_executables=frozenset({"allowed"}),
        cwd=".",
        token=AsyncCancellationToken(),
        output_budget=TextOutputBudget(max_lines=2, max_bytes=100),
    )
