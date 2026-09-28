"""Run cancellation is ID-scoped, joined, and keeps timed-out cleanup busy."""

import asyncio

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.server.sessions import SessionCoordinator, session_recovery_phase


def test_cancel_requires_matching_run_id_and_joins_the_owned_task() -> None:
    coordinator = SessionCoordinator()
    started = asyncio.Event()
    lease = coordinator.try_claim_run("session-1", "run-current")

    async def scenario() -> None:
        async def operation(_token: AsyncCancellationToken) -> None:
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(coordinator.run(lease, operation))
        await started.wait()
        assert await coordinator.cancel_run("session-1", "run-old") == "not_found"
        assert coordinator.is_busy("session-1")
        assert await coordinator.cancel_run("session-1", "run-current") == "cancelled"
        await asyncio.gather(task, return_exceptions=True)
        assert not coordinator.is_busy("session-1")

    asyncio.run(scenario())


def test_completed_run_cannot_be_relabelled_as_cancelled_before_release_callback() -> None:
    coordinator = SessionCoordinator()
    lease = coordinator.try_claim_run("session-1", "run-1")

    async def scenario() -> None:
        async def completed() -> None:
            return None

        task = asyncio.create_task(completed())
        lease.task = task
        await task

        assert coordinator.is_busy("session-1")
        assert await coordinator.cancel_run("session-1", "run-1") == "not_found"
        assert not lease.cancellation_token.cancelled
        assert not coordinator.is_busy("session-1")

    asyncio.run(scenario())


def test_cleanup_timeout_keeps_session_busy_until_task_really_exits() -> None:
    coordinator = SessionCoordinator(cleanup_timeout_seconds=0.01)
    started = asyncio.Event()
    cancel_seen = asyncio.Event()
    finish_cleanup = asyncio.Event()
    lease = coordinator.try_claim_run("session-1", "run-1")

    async def scenario() -> None:
        async def operation(_token: AsyncCancellationToken) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_seen.set()
                await finish_cleanup.wait()

        task = asyncio.create_task(coordinator.run(lease, operation))
        await started.wait()
        assert await coordinator.cancel_run("session-1", "run-1") == "needs_recovery"
        await cancel_seen.wait()
        assert coordinator.is_busy("session-1")
        finish_cleanup.set()
        await task
        assert not coordinator.is_busy("session-1")

    asyncio.run(scenario())


def test_pending_checkpoint_after_restart_requires_recovery_not_replay() -> None:
    assert session_recovery_phase(has_pending_checkpoint=True) == "needs_recovery"
    assert session_recovery_phase(has_pending_checkpoint=False) == "idle"
