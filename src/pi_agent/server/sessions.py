"""In-process ownership of one active run per session."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from pi_agent.runtime.cancellation import AsyncCancellationToken

T = TypeVar("T")
CancelResult = Literal["cancelled", "needs_recovery", "not_found"]


class SessionBusyError(RuntimeError):
    """A session already has an active run and cannot accept another prompt."""


@dataclass(slots=True)
class RunLease:
    """One session's temporary run ownership and its cancellation channel."""

    session_id: str
    run_id: str
    cancellation_token: AsyncCancellationToken = field(default_factory=AsyncCancellationToken)
    task: asyncio.Task[object] | None = None


class SessionCoordinator:
    """Keep session-level task ownership local to one server process."""

    def __init__(self, *, cleanup_timeout_seconds: float = 2.0) -> None:
        if (
            isinstance(cleanup_timeout_seconds, bool)
            or not isinstance(cleanup_timeout_seconds, (int, float))
            or not math.isfinite(cleanup_timeout_seconds)
            or cleanup_timeout_seconds <= 0
        ):
            raise ValueError("cleanup_timeout_seconds must be a positive finite number.")
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._active: dict[str, RunLease] = {}

    def try_claim_run(self, session_id: str, run_id: str, /) -> RunLease:
        """原子领取一个 session, 已被占用时抛出 ``SessionBusyError``。"""
        # 校验服务端关联标识, 拒绝空值/非字符串/首尾带空白的值.
        if not isinstance(session_id, str) or not session_id or session_id != session_id.strip():
            raise ValueError(
                "session_id must be a non-empty string without surrounding whitespace."
            )
        if not isinstance(run_id, str) or not run_id or run_id != run_id.strip():
            raise ValueError("run_id must be a non-empty string without surrounding whitespace.")

        # 当前方法没有 await. 检查与登记在同一个 event loop 执行片段内完成.
        if session_id in self._active:
            raise SessionBusyError("Session already has an active run.")

        # 只创建并登记一个 lease. 后续 run/cancel 通过对象身份确认它仍是当前所有者.
        lease = RunLease(session_id=session_id, run_id=run_id)
        self._active[session_id] = lease
        return lease

    async def run(
        self,
        lease: RunLease,
        operation: Callable[[AsyncCancellationToken], Awaitable[T]],
        /,
    ) -> T:
        """Start one operation under a current lease and release after task exit."""
        if self._active.get(lease.session_id) is not lease or lease.task is not None:
            raise RuntimeError("Run lease is stale or already started.")

        async def invoke() -> T:
            return await operation(lease.cancellation_token)

        task: asyncio.Task[T] = asyncio.create_task(invoke())
        lease.task = task
        task.add_done_callback(lambda _task: self._release_if_current(lease))
        try:
            return await task
        finally:
            if task.done():
                self._release_if_current(lease)

    async def cancel_run(self, session_id: str, run_id: str, /) -> CancelResult:
        """Cancel only the matching run; retain ownership if cleanup times out."""
        lease = self._active.get(session_id)
        if lease is None or lease.run_id != run_id:
            return "not_found"

        task = lease.task
        if task is not None and task.done():
            # Completion won the race, even if its release callback has not run yet.
            self._release_if_current(lease)
            return "not_found"

        lease.cancellation_token.cancel()
        if task is None:
            self._release_if_current(lease)
            return "cancelled"

        task.cancel()
        done, _pending = await asyncio.wait({task}, timeout=self._cleanup_timeout_seconds)
        if not done:
            return "needs_recovery"

        self._release_if_current(lease)
        return "cancelled"

    def is_busy(self, session_id: str, /) -> bool:
        """Return whether this process still owns a run or its cleanup."""
        return session_id in self._active

    def _release_if_current(self, lease: RunLease) -> None:
        if self._active.get(lease.session_id) is lease:
            self._active.pop(lease.session_id)


def session_recovery_phase(*, has_pending_checkpoint: bool) -> Literal["idle", "needs_recovery"]:
    """Never replay a persisted partial run automatically after process restart."""
    return "needs_recovery" if has_pending_checkpoint else "idle"
