"""The dispatcher maps each validated command to one correlated response."""

import asyncio
from pathlib import Path

import pytest

from pi_agent.protocol.messages import (
    ClientRequest,
    DisplayMessage,
    ProtocolError,
    RunStartedEvent,
    SessionSnapshot,
)
from pi_agent.runtime.session import SessionRuntimeConfig
from pi_agent.server.dispatcher import (
    ServerCommandFailure,
    ServerCommandService,
    ServerDispatcher,
)
from pi_agent.server.sessions import SessionCoordinator
from pi_agent.sessions.metadata import SessionRecord


class MemoryCatalog:
    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}

    def record_session(self, session_id: str) -> SessionRecord:
        record = SessionRecord(session_id, "created", "updated")
        self.records[session_id] = record
        return record

    def list_sessions(self) -> list[SessionRecord]:
        return list(self.records.values())


class MemoryRuntime:
    def __init__(self, *, fail_prompt: bool = False) -> None:
        self.fail_prompt = fail_prompt
        self.prompt_calls: list[tuple[str, str, str | None]] = []
        self.snapshot_calls: list[tuple[str, int, str | None]] = []

    async def prompt(
        self, config: SessionRuntimeConfig, *, content: str, message_id: str
    ) -> object:
        self.prompt_calls.append((config.session_id, content, config.run_id))
        if self.fail_prompt:
            raise RuntimeError("provider secret must not be returned")
        return object()

    async def snapshot(
        self,
        config: SessionRuntimeConfig,
        *,
        revision: int,
        run_phase: str = "idle",
        run_outcome: str | None = None,
        active_run_id: str | None = None,
    ) -> SessionSnapshot:
        self.snapshot_calls.append((config.session_id, revision, active_run_id))
        return SessionSnapshot(
            session_id=config.session_id,
            server_epoch="epoch-1",
            revision=revision,
            checkpoint_id=None,
            graph_status="idle",
            run_phase=run_phase,  # type: ignore[arg-type]
            run_outcome=run_outcome,  # type: ignore[arg-type]
            active_run_id=active_run_id,
            message_count=0,
            messages=(DisplayMessage(message_id="message-1", role="assistant", text="ready"),),
            truncated=False,
        )


def _make_dispatcher(
    *,
    ids: tuple[str, ...] = ("session-new", "run-new", "message-new"),
    runtime: MemoryRuntime | None = None,
    catalog: MemoryCatalog | None = None,
    coordinator: SessionCoordinator | None = None,
) -> tuple[ServerDispatcher, MemoryRuntime, MemoryCatalog, SessionCoordinator]:
    runtime_value = runtime or MemoryRuntime()
    catalog_value = catalog or MemoryCatalog()
    coordinator_value = coordinator or SessionCoordinator()
    sequence = iter(ids)
    service = ServerCommandService(
        runtime=runtime_value,
        catalog=catalog_value,
        coordinator=coordinator_value,
        database=Path("database.sqlite"),
        workspace=Path("workspace"),
        id_factory=lambda: next(sequence),
    )
    return ServerDispatcher(service), runtime_value, catalog_value, coordinator_value


def _request_id(command: dict[str, object], request_id: int = 7) -> ClientRequest:
    return ClientRequest.model_validate(
        {"type": "request", "request_id": request_id, "request": command}
    )


async def _no_event(_event: object) -> None:
    return None


def test_create_session_records_before_returning_correlated_response() -> None:
    dispatcher, _runtime, catalog, _coordinator = _make_dispatcher()
    request = _request_id({"command": "create_session"}, request_id=41)

    response = asyncio.run(dispatcher.dispatch_message(request, send_event=_no_event))

    assert response.request_id == 41
    assert response.command == "create_session"
    assert response.ok is True
    assert response.snapshot is not None
    assert response.snapshot.session_id == "session-new"
    assert list(catalog.records) == ["session-new"]


def test_get_snapshot_rejects_unknown_session_without_runtime_call() -> None:
    dispatcher, runtime, _catalog, _coordinator = _make_dispatcher()
    request = _request_id({"command": "get_snapshot", "session_id": "missing"})

    response = asyncio.run(dispatcher.dispatch_message(request, send_event=_no_event))

    assert response.request_id == 7
    assert response.command == "get_snapshot"
    assert response.ok is False
    assert response.error == ProtocolError(code="not_found", message="Session was not found.")
    assert runtime.snapshot_calls == []


def test_prompt_forwards_run_event_and_returns_one_correlated_snapshot() -> None:
    catalog = MemoryCatalog()
    catalog.record_session("session-1")
    dispatcher, runtime, _catalog, _coordinator = _make_dispatcher(
        ids=("run-1", "message-1"), catalog=catalog
    )
    request = _request_id(
        {"command": "prompt", "session_id": "session-1", "text": "Read probe.txt"},
        request_id=12,
    )
    events: list[object] = []

    async def send_event(event: object) -> None:
        events.append(event)

    response = asyncio.run(dispatcher.dispatch_message(request, send_event=send_event))

    assert response.request_id == 12
    assert response.command == "prompt"
    assert response.ok is True
    assert response.snapshot is not None
    assert response.snapshot.run_outcome == "completed"
    assert events == [
        RunStartedEvent(
            type="event",
            event="run_started",
            request_id=12,
            session_id="session-1",
            run_id="run-1",
        )
    ]
    assert runtime.prompt_calls == [("session-1", "Read probe.txt", "run-1")]


def test_cancel_routes_run_id_and_returns_snapshot() -> None:
    catalog = MemoryCatalog()
    catalog.record_session("session-1")
    coordinator = SessionCoordinator()
    coordinator.try_claim_run("session-1", "run-1")
    dispatcher, _runtime, _catalog, _coordinator = _make_dispatcher(
        catalog=catalog, coordinator=coordinator
    )
    request = _request_id(
        {"command": "cancel", "session_id": "session-1", "run_id": "run-1"},
        request_id=19,
    )

    response = asyncio.run(dispatcher.dispatch_message(request, send_event=_no_event))

    assert response.request_id == 19
    assert response.command == "cancel"
    assert response.ok is True
    assert not coordinator.is_busy("session-1")


def test_model_failure_is_distinct_and_does_not_leak_exception_text() -> None:
    catalog = MemoryCatalog()
    catalog.record_session("session-1")
    dispatcher, _runtime, _catalog, _coordinator = _make_dispatcher(
        ids=("run-1", "message-1"),
        catalog=catalog,
        runtime=MemoryRuntime(fail_prompt=True),
    )
    request = _request_id({"command": "prompt", "session_id": "session-1", "text": "hello"})

    response = asyncio.run(dispatcher.dispatch_message(request, send_event=_no_event))

    assert response.request_id == 7
    assert response.command == "prompt"
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "internal_error"
    assert "secret" not in response.error.message


def test_process_active_run_limit_rejects_another_session_without_waiting() -> None:
    class GatedRuntime(MemoryRuntime):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.finish = asyncio.Event()

        async def prompt(
            self, config: SessionRuntimeConfig, *, content: str, message_id: str
        ) -> object:
            self.prompt_calls.append((config.session_id, content, config.run_id))
            self.started.set()
            await self.finish.wait()
            return object()

    async def scenario() -> None:
        runtime = GatedRuntime()
        catalog = MemoryCatalog()
        catalog.record_session("session-1")
        catalog.record_session("session-2")
        coordinator = SessionCoordinator()
        ids = iter(("run-1", "message-1", "run-2"))
        service = ServerCommandService(
            runtime=runtime,
            catalog=catalog,
            coordinator=coordinator,
            database=Path("database.sqlite"),
            workspace=Path("workspace"),
            max_active_runs=1,
            id_factory=lambda: next(ids),
        )

        async def ignore_event(_event: object) -> None:
            return None

        first = asyncio.create_task(
            service.prompt("session-1", "first", request_id=1, send_event=ignore_event)
        )
        await runtime.started.wait()
        with pytest.raises(ServerCommandFailure, match="capacity"):
            await service.prompt("session-2", "second", request_id=2, send_event=ignore_event)
        assert coordinator.is_busy("session-1")
        assert not coordinator.is_busy("session-2")
        runtime.finish.set()
        await first

    asyncio.run(scenario())
