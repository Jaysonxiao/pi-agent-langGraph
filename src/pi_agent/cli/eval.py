"""CLI entry point for deterministic fake evaluation suites."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from typing import TextIO, cast

from pi_agent.closing import close_iterator
from pi_agent.domain import create_initial_state
from pi_agent.evals import EvalCase, EvalHarness, EvalObservation, EvalSuite
from pi_agent.events import iter_terminal_once, project_stream_chunks, run_outcome
from pi_agent.events.stream import StreamEvent
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models import FakeChatModel

SMOKE_SUITE = EvalSuite(
    name="smoke",
    cases=(
        EvalCase(
            case_id="fake-smoke",
            prompt="hello",
            expected_response="fake reply",
            expected_tool_names=(),
        ),
    ),
)


class FakeGraphEvalExecutor:
    """Run eval cases through the existing offline fake graph."""

    async def run(self, case: EvalCase) -> EvalObservation:
        """Execute one case and keep only judge inputs in memory."""
        response = ""
        tool_names: list[str] = []
        raw_chunks = cast(
            Iterable[tuple[str, object]],
            build_minimal_graph().stream(
                create_initial_state(case.prompt),
                context=RunContext(model=FakeChatModel()),
                stream_mode=["updates", "messages", "custom"],
            ),
        )
        events = iter_terminal_once(project_stream_chunks(raw_chunks))
        try:
            for event in events:
                if event.kind == "message" and event.payload.get("role") == "assistant":
                    content = event.payload.get("content")
                    if isinstance(content, str):
                        response += content
                elif event.kind == "tool":
                    tool_names.extend(_tool_names(event))
                if run_outcome(event) is not None:
                    break
        finally:
            close_iterator(events)
            close_iterator(raw_chunks)
        return EvalObservation(response=response, tool_names=tuple(tool_names))


def add_eval_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the M9 fake eval command."""
    eval_parser = commands.add_parser("eval")
    eval_parser.add_argument("--suite", choices=(SMOKE_SUITE.name,), required=True)
    eval_parser.add_argument("--provider", choices=("fake",), required=True)


def run_eval_cli(args: argparse.Namespace, output: TextIO) -> int:
    """Run a deterministic fake suite and write one safe JSON report."""
    if args.suite != SMOKE_SUITE.name:
        raise ValueError(f"Unsupported eval suite: {args.suite}")
    if args.provider != "fake":
        raise ValueError("Eval CLI only supports the fake provider in this slice.")

    report = asyncio.run(EvalHarness(FakeGraphEvalExecutor()).run(SMOKE_SUITE))
    output.write(report.to_json() + "\n")
    output.flush()
    return 0 if report.passed == report.total else 1


def _tool_names(event: StreamEvent) -> tuple[str, ...]:
    """Extract ordered tool names when the projected payload exposes them."""
    names = event.payload.get("tool_names")
    if isinstance(names, list) and all(isinstance(name, str) for name in names):
        return tuple(names)
    name = event.payload.get("tool_name")
    if isinstance(name, str):
        return (name,)
    # 当前 fake smoke 不走工具; 这里保留投影入口, 后续接真实工具事件时无需改报告契约。
    return ()
