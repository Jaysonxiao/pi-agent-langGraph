"""Acceptance tests for cooperative CLI stream cancellation."""

from collections.abc import Iterator

from pi_agent.cli import CancellationToken, iter_cancellable


class _CloseTrackingIterator:
    """Track teardown without relying on an unstarted generator's finally block."""

    def __init__(self) -> None:
        self.next_calls = 0
        self.close_calls = 0

    def __iter__(self) -> "_CloseTrackingIterator":
        return self

    def __next__(self) -> int:
        self.next_calls += 1
        return 1

    def close(self) -> None:
        self.close_calls += 1


def _tracked_source(closed: list[bool]) -> Iterator[int]:
    try:
        yield 1
        yield 2
        yield 3
    finally:
        closed.append(True)


def test_cancellation_token_is_idempotent() -> None:
    token = CancellationToken()

    assert not token.cancelled
    token.cancel()
    token.cancel()
    assert token.cancelled


def test_cancellation_before_consumption_closes_without_starting_upstream() -> None:
    source = _CloseTrackingIterator()
    token = CancellationToken()
    token.cancel()

    assert list(iter_cancellable(source, token)) == []
    assert source.next_calls == 0
    assert source.close_calls == 1


def test_cancellation_after_one_event_stops_and_closes_upstream() -> None:
    closed: list[bool] = []
    token = CancellationToken()
    events = iter_cancellable(_tracked_source(closed), token)

    assert next(events) == 1
    token.cancel()
    assert list(events) == []
    assert closed == [True]
