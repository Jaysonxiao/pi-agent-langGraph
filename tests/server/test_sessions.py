"""Session claims are isolated by session and released only after owned work ends."""

import asyncio

import pytest

from pi_agent.server.sessions import (
    RunLease,
    SessionBusyError,
    SessionCoordinator,
)


def test_one_session_has_one_lease_and_different_sessions_can_be_claimed() -> None:
    coordinator = SessionCoordinator()

    first = coordinator.try_claim_run("session-1", "run-1")
    other = coordinator.try_claim_run("session-2", "run-2")

    assert isinstance(first, RunLease)
    assert isinstance(other, RunLease)
    assert first is not other
    with pytest.raises(SessionBusyError):
        coordinator.try_claim_run("session-1", "run-3")


@pytest.mark.parametrize(
    ("session_id", "run_id"),
    [("", "run-1"), ("session-1", "  ")],
)
def test_claim_rejects_blank_session_or_run_id(session_id: str, run_id: str) -> None:
    with pytest.raises(ValueError):
        SessionCoordinator().try_claim_run(session_id, run_id)


def test_session_becomes_available_only_after_owned_task_finishes() -> None:
    coordinator = SessionCoordinator()
    started = asyncio.Event()
    finish = asyncio.Event()
    lease = coordinator.try_claim_run("session-1", "run-1")

    async def scenario() -> None:
        async def operation(_token: object) -> str:
            started.set()
            await finish.wait()
            return "done"

        task = asyncio.create_task(coordinator.run(lease, operation))
        await started.wait()
        assert coordinator.is_busy("session-1")
        with pytest.raises(SessionBusyError):
            coordinator.try_claim_run("session-1", "run-2")
        finish.set()
        assert await task == "done"
        assert not coordinator.is_busy("session-1")

    asyncio.run(scenario())
