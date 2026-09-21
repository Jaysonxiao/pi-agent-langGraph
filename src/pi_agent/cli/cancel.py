"""Cooperative cancellation boundary for CLI event streams."""

from collections.abc import Iterable, Iterator
from typing import TypeVar

from pi_agent.closing import close_iterator

_T = TypeVar("_T")


class CancellationToken:
    """Small, explicit cancellation state shared by a producer and consumer."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Request cancellation; repeated calls remain harmless."""

        self._cancelled = True


def iter_cancellable(events: Iterable[_T], token: CancellationToken) -> Iterator[_T]:
    """Yield events until cancellation, closing an upstream iterator when possible."""

    iterator = iter(events)
    try:
        while not token.cancelled:
            # 先看 token 再 next(), 避免取消后又多消费一条; 也不为 close 去 next.
            try:
                item = next(iterator)
            except StopIteration:
                break
            yield item
    finally:
        close_iterator(iterator)
