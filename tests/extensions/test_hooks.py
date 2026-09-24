"""Contract tests for the learner-owned M9.1 hook dispatcher."""

import asyncio

import pytest

from pi_agent.extensions import HookEvent, HookFailure, HookRegistry


def _before_model_event() -> HookEvent:
    return HookEvent(
        phase="before_model",
        thread_id="thread-1",
        run_id="run-1",
        sequence=1,
        node="model",
    )


def test_event_rejects_invalid_tool_identity() -> None:
    with pytest.raises(ValueError, match="tool_name and tool_call_id"):
        HookEvent(
            phase="before_tool",
            thread_id="thread-1",
            run_id="run-1",
            sequence=2,
            node="tools",
            tool_name="read",
        )

    with pytest.raises(ValueError, match="must not include tool identity"):
        HookEvent(
            phase="before_model",
            thread_id="thread-1",
            run_id="run-1",
            sequence=1,
            node="model",
            tool_name="read",
            tool_call_id="call-1",
        )


def test_registry_preserves_unique_registration_order() -> None:
    registry = HookRegistry()

    async def first(_event: HookEvent) -> None:
        return None

    async def second(_event: HookEvent) -> None:
        return None

    registry.register("first", first)
    registry.register("second", second)

    assert registry.names == ("first", "second")
    with pytest.raises(ValueError, match="Duplicate hook name: first"):
        registry.register("first", first)


def test_dispatch_preserves_order_isolates_failures_and_redacts_messages() -> None:
    registry = HookRegistry()
    calls: list[str] = []
    secret = "sk-m9-synthetic-secret"

    async def first(_event: HookEvent) -> None:
        calls.append("first")

    async def broken(_event: HookEvent) -> None:
        calls.append("broken")
        raise RuntimeError(f"provider rejected {secret}")

    async def last(_event: HookEvent) -> None:
        calls.append("last")

    registry.register("first", first)
    registry.register("broken", broken)
    registry.register("last", last)

    result = asyncio.run(registry.dispatch(_before_model_event()))

    assert calls == ["first", "broken", "last"]
    assert result.failures == (
        HookFailure(
            hook_name="broken",
            phase="before_model",
            exception_type="RuntimeError",
        ),
    )
    assert secret not in repr(result)


def test_dispatch_uses_registration_snapshot() -> None:
    registry = HookRegistry()
    calls: list[str] = []

    async def late(_event: HookEvent) -> None:
        calls.append("late")

    async def registering(_event: HookEvent) -> None:
        calls.append("registering")
        if "late" not in registry.names:
            registry.register("late", late)

    registry.register("registering", registering)

    first_result = asyncio.run(registry.dispatch(_before_model_event()))
    second_result = asyncio.run(registry.dispatch(_before_model_event()))

    assert first_result.failures == ()
    assert second_result.failures == ()
    assert calls == ["registering", "registering", "late"]


def test_dispatch_propagates_cancellation_and_stops_later_handlers() -> None:
    registry = HookRegistry()
    calls: list[str] = []

    async def cancelled(_event: HookEvent) -> None:
        calls.append("cancelled")
        raise asyncio.CancelledError

    async def must_not_run(_event: HookEvent) -> None:
        calls.append("must-not-run")

    registry.register("cancelled", cancelled)
    registry.register("must-not-run", must_not_run)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(registry.dispatch(_before_model_event()))

    assert calls == ["cancelled"]
