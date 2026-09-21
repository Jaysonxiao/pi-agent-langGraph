"""Acceptance tests for publishing terminal state only once."""

from typing import Literal

from pi_agent.events import StreamEvent, iter_terminal_once, run_outcome

_Kind = Literal["state_update", "tool", "message", "error"]


def _event(sequence: int, kind: _Kind, status: str | None = None) -> StreamEvent:
    payload: dict[str, object] = {"status": status} if status is not None else {}
    return StreamEvent(sequence=sequence, kind=kind, node="model", payload=payload)


def test_terminal_filter_stops_after_first_terminal_state() -> None:
    events = [
        _event(0, "state_update", "awaiting_tools"),
        _event(1, "message"),
        _event(2, "state_update", "completed"),
        _event(3, "state_update", "completed"),
        _event(4, "tool", "ready"),
        _event(5, "state_update", "failed"),
    ]

    assert list(iter_terminal_once(events)) == [events[0], events[1], events[2]]


def test_terminal_filter_keeps_a_failed_terminal_state_once() -> None:
    events = [_event(0, "state_update", "failed"), _event(1, "state_update", "completed")]

    assert list(iter_terminal_once(events)) == [events[0]]


def test_terminal_filter_recognizes_projected_error_and_stops() -> None:
    events = [
        _event(0, "error", "failed"),
        _event(1, "error", "failed"),
        _event(2, "message"),
    ]

    assert list(iter_terminal_once(events)) == [events[0]]
    assert run_outcome(events[0]) == "failure"


def test_run_outcome_distinguishes_success_failure_and_non_terminal() -> None:
    assert run_outcome(_event(0, "state_update", "completed")) == "success"
    assert run_outcome(_event(1, "state_update", "failed")) == "failure"
    assert run_outcome(_event(2, "state_update", "ready")) is None
