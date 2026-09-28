"""Route validated protocol requests to server-owned session operations."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from pi_agent.protocol.messages import (
    ClientRequest,
    ProtocolError,
    RunStartedEvent,
    ServerEvent,
    ServerResponse,
    SessionSnapshot,
)
from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.session import SessionRuntimeConfig
from pi_agent.server.sessions import SessionBusyError, SessionCoordinator
from pi_agent.sessions.metadata import SessionCatalog, SessionRecord

ErrorCode = Literal[
    "unsupported_version",
    "invalid_request",
    "unauthorized",
    "not_found",
    "busy",
    "needs_recovery",
    "internal_error",
]
EventSender = Callable[[ServerEvent], Awaitable[None]]


class ServerCommandFailure(RuntimeError):
    """A safe, typed command failure that is suitable for a protocol response."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class SessionRuntime(Protocol):
    """The small execution boundary used by protocol command routing."""

    async def prompt(
        self, config: SessionRuntimeConfig, *, content: str, message_id: str
    ) -> object: ...

    async def snapshot(
        self,
        config: SessionRuntimeConfig,
        *,
        revision: int,
        run_phase: str = "idle",
        run_outcome: str | None = None,
        active_run_id: str | None = None,
    ) -> SessionSnapshot: ...


class RemoteSessionCatalog(SessionCatalog, Protocol):
    """Read durable session existence without exposing checkpoint internals."""

    def list_sessions(self) -> list[SessionRecord]: ...


class ServerCommandService:
    """Bind client commands to server-owned catalog, runtime, and run leases."""

    def __init__(
        self,
        *,
        runtime: SessionRuntime,
        catalog: RemoteSessionCatalog,
        coordinator: SessionCoordinator,
        database: Path,
        workspace: Path,
        max_active_runs: int = 4,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if isinstance(max_active_runs, bool) or not isinstance(max_active_runs, int):
            raise ValueError("max_active_runs must be an integer.")
        if not 1 <= max_active_runs <= 4:
            raise ValueError("max_active_runs must be between 1 and 4.")
        self._runtime = runtime
        self._catalog = catalog
        self._coordinator = coordinator
        self._database = database
        self._workspace = workspace
        self._max_active_runs = max_active_runs
        self._new_id = id_factory or (lambda: uuid4().hex)
        self._active_run_count = 0
        self._active_runs: dict[str, str] = {}
        self._run_outcomes: dict[str, Literal["completed", "failed", "cancelled"]] = {}
        self._revisions: dict[str, int] = {}

    async def create_session(self) -> SessionSnapshot:
        session_id = self._new_id()
        try:
            await asyncio.to_thread(self._catalog.record_session, session_id)
        except Exception:
            raise ServerCommandFailure("internal_error", "Could not create the session.") from None
        self._revisions[session_id] = 0
        return await self._snapshot(session_id)

    async def get_snapshot(self, session_id: str) -> SessionSnapshot:
        await self._require_session(session_id)
        return await self._snapshot(session_id)

    async def prompt(
        self,
        session_id: str,
        text: str,
        *,
        request_id: int,
        send_event: EventSender,
    ) -> SessionSnapshot:
        await self._require_session(session_id)
        run_id = self._new_id()
        try:
            lease = self._coordinator.try_claim_run(session_id, run_id)
        except SessionBusyError:
            raise ServerCommandFailure("busy", "Session already has an active run.") from None

        # This synchronous reservation is the process-wide active-run limit.
        if self._active_run_count >= self._max_active_runs:
            await self._coordinator.cancel_run(session_id, run_id)
            raise ServerCommandFailure("busy", "Server active-run capacity is full.")

        self._active_run_count += 1
        self._active_runs[session_id] = run_id
        self._revisions[session_id] = self._revisions.get(session_id, 0) + 1
        config = self._runtime_config(session_id, run_id, lease.cancellation_token)
        outcome: Literal["completed", "failed", "cancelled"] = "failed"
        try:
            await send_event(
                RunStartedEvent(
                    type="event",
                    event="run_started",
                    request_id=request_id,
                    session_id=session_id,
                    run_id=run_id,
                )
            )
            result = await self._coordinator.run(
                lease,
                lambda _token: self._runtime.prompt(
                    config,
                    content=text,
                    message_id=self._new_id(),
                ),
            )
            outcome = (
                "failed"
                if isinstance(result, dict) and result.get("status") == "failed"
                else "completed"
            )
        except asyncio.CancelledError:
            outcome = "cancelled"
        except Exception:
            self._run_outcomes[session_id] = "failed"
            raise ServerCommandFailure("internal_error", "The model run failed.") from None
        finally:
            # If disconnect happened before run() installed its owned task,
            # release the not-yet-started lease explicitly.
            if lease.task is None and self._coordinator.is_busy(session_id):
                await self._coordinator.cancel_run(session_id, run_id)
            self._run_outcomes[session_id] = outcome
            if self._active_runs.get(session_id) == run_id:
                self._active_runs.pop(session_id)
            self._active_run_count -= 1
            self._revisions[session_id] = self._revisions.get(session_id, 0) + 1
        return await self._snapshot(session_id)

    async def cancel(self, session_id: str, run_id: str) -> SessionSnapshot:
        await self._require_session(session_id)
        result = await self._coordinator.cancel_run(session_id, run_id)
        if result == "not_found":
            raise ServerCommandFailure("not_found", "Active run was not found.")
        if result == "needs_recovery":
            raise ServerCommandFailure("needs_recovery", "Run cleanup has not finished.")
        self._run_outcomes[session_id] = "cancelled"
        self._revisions[session_id] = self._revisions.get(session_id, 0) + 1
        return await self._snapshot(session_id)

    async def _require_session(self, session_id: str) -> None:
        try:
            records = await asyncio.to_thread(self._catalog.list_sessions)
        except Exception:
            raise ServerCommandFailure(
                "internal_error", "Could not read session records."
            ) from None
        if not any(record.session_id == session_id for record in records):
            raise ServerCommandFailure("not_found", "Session was not found.")

    async def _snapshot(self, session_id: str) -> SessionSnapshot:
        return await self._runtime.snapshot(
            self._runtime_config(session_id),
            revision=self._revisions.get(session_id, 0),
            run_phase="running" if session_id in self._active_runs else "idle",
            run_outcome=self._run_outcomes.get(session_id),
            active_run_id=self._active_runs.get(session_id),
        )

    def _runtime_config(
        self,
        session_id: str,
        run_id: str | None = None,
        cancellation_token: AsyncCancellationToken | None = None,
    ) -> SessionRuntimeConfig:
        return SessionRuntimeConfig(
            database=self._database,
            workspace=self._workspace,
            session_id=session_id,
            run_id=run_id,
            cancellation_token=cancellation_token or AsyncCancellationToken(),
        )


class ServerDispatcher:
    """Map one validated request to one service call and one final response."""

    def __init__(self, service: ServerCommandService) -> None:
        self._service = service

    async def cancel_owned_run(self, session_id: str, run_id: str, /) -> None:
        """Cancel a connection-owned run and wait within the coordinator bound."""
        try:
            await self._service.cancel(session_id, run_id)
        except ServerCommandFailure:
            # not_found/needs_recovery are safe terminal outcomes for disconnect;
            # SessionCoordinator continues to hold busy while cleanup is pending.
            return

    async def dispatch_message(
        self,
        request: ClientRequest,
        *,
        send_event: EventSender,
    ) -> ServerResponse:
        """路由一条已校验请求,并在唯一响应中保留 request ID 与 command。"""
        command = request.request
        try:
            # 依据严格 DTO 的 discriminator 分派,协议模型负责在进入此处前校验字段。
            if command.command == "create_session":
                snapshot = await self._service.create_session()
            elif command.command == "get_snapshot":
                snapshot = await self._service.get_snapshot(command.session_id)
            elif command.command == "prompt":
                # prompt 产生的 run_started 事件必须关联原请求 ID,并通过连接发送器发出。
                snapshot = await self._service.prompt(
                    command.session_id,
                    command.text,
                    request_id=request.request_id,
                    send_event=send_event,
                )
            elif command.command == "cancel":
                snapshot = await self._service.cancel(command.session_id, command.run_id)
            else:
                # 防御未来新增但尚未接入的命令类型,不将内部异常细节返回客户端。
                return _error_response(
                    request, "internal_error", "The requested command is unavailable."
                )
        except ServerCommandFailure as failure:
            # 该异常仅携带服务层声明为安全的协议错误码和文案。
            return _error_response(request, failure.code, failure.safe_message)
        except Exception:
            # 未预期异常统一收敛,避免 provider、存储或实现细节泄漏到网络响应。
            return _error_response(request, "internal_error", "Internal server error.")

        return ServerResponse(
            type="response",
            request_id=request.request_id,
            command=command.command,
            ok=True,
            snapshot=snapshot,
        )


def _error_response(request: ClientRequest, code: ErrorCode, message: str) -> ServerResponse:
    return ServerResponse(
        type="response",
        request_id=request.request_id,
        command=request.request.command,
        ok=False,
        error=ProtocolError(code=code, message=message),
    )
