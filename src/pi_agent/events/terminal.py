"""Terminal-state filtering for the CLI event boundary."""

from collections.abc import Iterable, Iterator
from typing import Literal

from pi_agent.closing import close_iterator
from pi_agent.events.stream import StreamEvent

# 运行终态: completed/failed 的 state_update, 以及投影后的 error.
# awaiting_tools / tool ready 会多次出现, 不能当终态.
_TERMINAL_STATUSES = frozenset({"completed", "failed"})
RunOutcome = Literal["success", "failure"]


def is_run_terminal(event: StreamEvent) -> bool:
    """True for the first-class run terminal CLI should publish at most once."""

    if event.kind == "error":
        return True
    return event.kind == "state_update" and event.payload.get("status") in _TERMINAL_STATUSES


def run_outcome(event: StreamEvent) -> RunOutcome | None:
    """Map a terminal event to success/failure; non-terminals return None."""

    if not is_run_terminal(event):
        return None
    if event.kind == "error" or event.payload.get("status") == "failed":
        return "failure"
    return "success"


def iter_terminal_once(events: Iterable[StreamEvent]) -> Iterator[StreamEvent]:
    """Yield through the first run terminal, then close the upstream stream.

    Sequence numbers stay unchanged. A terminal event ends upstream consumption.
    """

    iterator = iter(events)
    try:
        for event in iterator:
            yield event
            if is_run_terminal(event):
                break
    finally:
        close_iterator(iterator)
