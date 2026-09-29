"""Single-user, same-origin HTTP/SSE entry point. Bind only to loopback."""

import argparse
import asyncio
import json
import os
import secrets
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.config import ModelOptions, resolve_model_config
from pi_agent.models.http_client import build_async_provider_client
from pi_agent.web.demo import DemoModel
from pi_agent.web.schemas import (
    MessagePage,
    NewRun,
    RunItem,
    SessionEdit,
    SessionItem,
    SessionView,
    SettingsUpdate,
    StepDetail,
)
from pi_agent.web.service import WebError, Workbench, project_history


def default_web_database() -> Path:
    """Keep checkpoints outside the default project workspace."""
    return Path.home() / ".pi-agent" / "web.sqlite"


def create_app(
    *,
    workspace: Path,
    database: Path,
    model: AsyncChatModel,
    provider: str = "fake",
    model_name: str | None = None,
    close_model: Callable[[], Awaitable[None]] | None = None,
    static_dir: Path | None = None,
    timeout: float = 120,
    request_timeout: float = 30,
    attempts: int = 3,
) -> FastAPI:
    workspace = workspace.resolve()
    database = database.expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError("Workspace must be an existing directory.")
    if database.is_relative_to(workspace):
        raise ValueError("Web database must be outside the workspace.")
    database.parent.mkdir(parents=True, exist_ok=True)
    cookie = secrets.token_urlsafe(32)
    # The lease prevents two web processes from maintaining competing in-memory coordinators.
    lease = FileLock(str(database) + ".web.lock", timeout=0)
    workbench = Workbench(
        database=database,
        workspace=workspace,
        model=model,
        timeout=timeout,
        request_timeout=request_timeout,
        attempts=attempts,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        lease.acquire()
        try:
            workbench.store.recover()
            yield
        finally:
            try:
                await workbench.close()
            finally:
                try:
                    if close_model is not None:
                        await close_model()
                finally:
                    lease.release()

    app = FastAPI(
        title="Pi Workbench", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.workbench = workbench
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if (origin is not None and origin != expected) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse({"detail": "不允许跨站访问。"}, status_code=403)
            bootstrap = request.url.path == "/api/bootstrap" and request.method == "GET"
            if (bootstrap or request.method not in {"GET", "HEAD"}) and request.headers.get(
                "x-pi-request"
            ) != "1":
                return JSONResponse({"detail": "请求校验失败。"}, status_code=403)
            if not bootstrap and not secrets.compare_digest(
                request.cookies.get("pi_web", ""), cookie
            ):
                return JSONResponse({"detail": "访问已过期, 请刷新页面。"}, status_code=401)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "请求格式不正确。"}, status_code=400)
            if length < 0 or length > 256 * 1024:
                return JSONResponse({"detail": "请求过大。"}, status_code=413)
            if request.method in {"POST", "PATCH", "PUT"}:
                # Also bound chunked bodies before Pydantic materializes user input.
                size = 0
                parts: list[bytes] = []
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 256 * 1024:
                        return JSONResponse({"detail": "请求过大。"}, status_code=413)
                    parts.append(chunk)
                request._body = b"".join(parts)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(WebError)
    async def web_error(_request: Request, error: WebError) -> JSONResponse:
        return JSONResponse({"detail": error.message}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"detail": "请求格式不正确或超过长度限制。"}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse({"detail": "服务暂时无法完成请求, 请稍后重试。"}, status_code=500)

    @app.get("/api/bootstrap")
    async def bootstrap() -> JSONResponse:
        response = JSONResponse(workbench.public_config(provider, model_name or "离线演示"))
        response.set_cookie("pi_web", cookie, httponly=True, samesite="strict", path="/api")
        return response

    @app.put("/api/settings")
    async def update_settings(settings: SettingsUpdate) -> JSONResponse:
        configured = await workbench.update_settings(settings)
        configured["provider"] = provider
        configured["model"] = model_name or "离线演示"
        configured["server_epoch"] = workbench.epoch
        return JSONResponse(configured)

    @app.get("/api/sessions")
    async def sessions(archived: bool = False) -> list[SessionItem]:
        return workbench.store.sessions(archived)

    @app.post("/api/sessions", status_code=201)
    async def create_session() -> SessionItem:
        from uuid import uuid4

        return workbench.store.create(uuid4().hex, workbench.workspace)

    @app.get("/api/sessions/{session_id}")
    async def session(session_id: str) -> SessionView:
        return await workbench.view(session_id)

    @app.patch("/api/sessions/{session_id}")
    async def edit_session(session_id: str, edit: SessionEdit) -> SessionItem:
        workbench.require_session(session_id)
        if workbench.coordinator.is_busy(session_id) and edit.archived:
            raise WebError(409, "请等待当前运行结束后再归档。")
        workbench.store.edit(session_id, edit)
        item = workbench.store.session(session_id)
        assert item is not None
        return item

    @app.get("/api/sessions/{session_id}/messages")
    async def messages(
        session_id: str,
        checkpoint: str = Query(min_length=1, max_length=255),
        before: int = Query(ge=0),
    ) -> MessagePage:
        state = await workbench.state(session_id, checkpoint)
        if state.created_at is None:
            raise WebError(404, "历史检查点不存在。")
        return project_history(state, before)

    @app.get("/api/sessions/{session_id}/activities/{event_id}")
    async def activity_detail(session_id: str, event_id: int) -> StepDetail:
        workbench.require_session(session_id)
        return await workbench.activity_detail(session_id, event_id)

    @app.post("/api/sessions/{session_id}/runs", status_code=202)
    async def start_run(session_id: str, request: NewRun) -> RunItem:
        return await workbench.start(session_id, request)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> RunItem:
        run = workbench.store.run(run_id)
        if run is None:
            raise WebError(404, "找不到这个运行。")
        return run

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str) -> RunItem:
        return await workbench.cancel(run_id)

    @app.get("/api/sessions/{session_id}/events")
    async def events(session_id: str, request: Request) -> StreamingResponse:
        workbench.require_session(session_id)

        async def stream() -> AsyncIterator[str]:
            # Always resync on connection: a bounded event log is not a complete run journal.
            initial = workbench.store.events(session_id)
            cursor = initial[-1].event_id if initial else 0
            yield f"event: sync\nid: {cursor}\ndata: {{}}\n\n"
            idle = 0
            while not workbench.closing and not await request.is_disconnected():
                pending = workbench.store.events(session_id, cursor)
                if pending:
                    cursor = pending[-1].event_id
                    payload = json.dumps(
                        [event.model_dump() for event in pending], ensure_ascii=False
                    )
                    yield f"event: activity\nid: {cursor}\ndata: {payload}\n\n"
                elif idle % 20 == 0:
                    yield ": heartbeat\n\n"
                idle += 1
                await asyncio.sleep(0.3)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "X-Accel-Buffering": "no",
                "Cache-Control": "no-cache",
            },
        )

    assets = static_dir or Path(__file__).with_name("static")
    if assets.is_dir():
        app.mount("/", StaticFiles(directory=assets, html=True), name="ui")
    else:

        @app.get("/")
        async def missing_build() -> JSONResponse:
            return JSONResponse(
                {"detail": "请先在 web-ui 目录运行 npm ci 和 npm run build。"}, status_code=503
            )

    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi-agent-web")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--database", type=Path, default=default_web_database())
    parser.add_argument("--provider", choices=["fake", "compatible"])
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    try:
        import uvicorn

        config = resolve_model_config(ModelOptions(provider=args.provider), os.environ)
        model: AsyncChatModel
        close_model: Callable[[], Awaitable[None]] | None = None
        if config.provider == "fake":
            model = DemoModel()
        else:
            compatible = CompatibleAsyncChatModel(build_async_provider_client(config))
            model, close_model = compatible, compatible.aclose
        app = create_app(
            workspace=args.workspace,
            database=args.database,
            model=model,
            provider=config.provider,
            model_name=config.model,
            close_model=close_model,
            timeout=config.run_timeout_seconds,
            request_timeout=config.timeout_seconds,
            attempts=config.max_attempts,
        )
        print(f"Pi Workbench: http://127.0.0.1:{args.port}")
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            timeout_graceful_shutdown=5,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        sys.stderr.write(f"Web startup or shutdown failed: {type(error).__name__}.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
