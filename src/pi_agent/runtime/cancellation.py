"""Explicit native-async cancellation signal owned by the runtime."""

import asyncio


class AsyncCancellationToken:
    """One-way cancellation request shared by async runtime collaborators."""

    def __init__(self) -> None:
        # Event.set() 本身幂等, 用来同时表达状态和唤醒 wait().
        self._event = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cancellation once; repeated calls must remain harmless."""
        self._event.set()

    async def wait(self) -> None:
        """Wait until cancellation is requested without polling."""
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        """Raise the native control signal, never a retryable business error."""
        if self._event.is_set():
            raise asyncio.CancelledError()
