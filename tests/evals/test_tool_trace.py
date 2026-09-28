"""Learner contracts: successful execution is different from a tool request."""

from dataclasses import replace

import pytest

from pi_agent.evals.tool_trace import collect_tool_names
from pi_agent.extensions import HookEvent


def _completed(name: str, call: str, sequence: int = 2) -> HookEvent:
    return HookEvent(
        phase="after_tool",
        thread_id="thread-1",
        run_id="run-1",
        sequence=sequence,
        node="tools",
        tool_name=name,
        tool_call_id=call,
        outcome="completed",
    )


def test_only_successful_tool_completions_count() -> None:
    read = _completed("read", "call-1")
    events = (
        replace(read, phase="before_tool", outcome=None),
        replace(read, outcome="failed"),
        replace(read, outcome="cancelled"),
        replace(read, outcome=None),
        HookEvent(phase="after_model", thread_id="thread-1", run_id="run-1", sequence=1),
        read,
    )
    assert collect_tool_names(events) == ("read",)


def test_duplicate_completion_does_not_double_count_but_repeated_name_does() -> None:
    read = _completed("read", "call-1")
    events = [read, read, _completed("search", "call-2"), _completed("read", "call-3")]
    before = events.copy()
    assert collect_tool_names(events) == ("read", "search", "read")
    assert events == before


def test_call_identity_is_scoped_to_thread_and_run_in_arrival_order() -> None:
    first = _completed("search", "reused-id", sequence=20)
    second = replace(first, run_id="run-2", tool_name="read", sequence=1)
    third = replace(second, thread_id="thread-2", tool_name="list", sequence=0)
    assert collect_tool_names((first, second, third, first)) == ("search", "read", "list")


@pytest.mark.parametrize(
    "events",
    [(), (_completed("read", "call-1"),)],
)
def test_no_successes_returns_empty(events: tuple[HookEvent, ...]) -> None:
    failed = tuple(replace(event, outcome="failed") for event in events)
    assert collect_tool_names(failed) == ()
