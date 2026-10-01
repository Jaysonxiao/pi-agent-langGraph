"""Explicit recovery, isolated branches, and preview/commit boundaries."""

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from tests.web.test_workbench import HEADERS, login, session, wait_run

from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.config import ModelOptions, resolve_model_config
from pi_agent.models.errors import ModelProviderError
from pi_agent.models.http_client import CompatibleHttpClient
from pi_agent.web.app import create_app
from pi_agent.web.demo import DemoModel
from pi_agent.web.schemas import CheckpointAction, NewRun, SessionEdit
from pi_agent.web.service import WebError, Workbench, project_history
from pi_agent.web.store import WebStore


class ControlledModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0
        self.closed = 0

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        return AIMessage(content="fallback")

    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        try:
            yield AIMessageChunk(content="first ")
            self.started.set()
            await self.release.wait()
            yield AIMessageChunk(content="complete")
        finally:
            self.closed += 1

    async def aclose(self) -> None:
        pass


def test_cancel_restart_explicit_resume_deduplicates_user_and_request(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        database = tmp_path / "web.sqlite"
        model = ControlledModel()
        workbench = Workbench(database=database, workspace=workspace, model=model)
        sid = workbench.store.create("resume-session").session_id
        run = await workbench.start(sid, NewRun(text="hello", request_id="initial-request"))
        await asyncio.wait_for(model.started.wait(), 3)
        view = await workbench.view(sid)
        assert view.preview is not None and view.preview.text == "first "
        assert all(message.role != "assistant" for message in view.history.messages)
        assert (await workbench.cancel(run.run_id)).status == "cancelled"
        assert model.closed == 1
        view = await workbench.view(sid)
        assert view.needs_recovery and view.preview is None
        checkpoint = view.history.checkpoint_id
        assert checkpoint is not None
        await workbench.close()

        model.release.set()
        reopened = Workbench(database=database, workspace=workspace, model=model)
        reopened.store.recover()
        assert model.calls == 1  # Restart never runs the graph.
        action = CheckpointAction(checkpoint_id=checkpoint, request_id="resume-request")
        resumed = await reopened.start(sid, action)
        assert (await reopened.start(sid, action)).run_id == resumed.run_id
        await asyncio.gather(*reopened.tasks.values())
        assert (await reopened.start(sid, action)).run_id == resumed.run_id
        final = await reopened.view(sid)
        assert final.run is not None and final.run.status == "completed"
        assert [message.role for message in final.history.messages] == ["user", "assistant"]
        assert final.history.messages[-1].text == "first complete"
        assert model.calls == 2 and not final.needs_recovery
        with pytest.raises(WebError, match="检查点"):
            await reopened.start(sid, action.model_copy(update={"request_id": "stale-request"}))
        await reopened.close()

    asyncio.run(scenario())


def test_legacy_run_receipt_migrates_and_operation_identity_is_preserved(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TABLE web_runs (run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
            "request_id TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL, finished_at TEXT, error TEXT, "
            "UNIQUE(session_id,request_id))"
        )
        connection.execute(
            "INSERT INTO web_runs VALUES (?,?,?,?,?,?,NULL,NULL)",
            (
                "legacy-run",
                "legacy-session",
                "legacy-request",
                hashlib.sha256(b"same").hexdigest(),
                "completed",
                "2026-09-29T00:00:00+00:00",
            ),
        )
    store = WebStore(database)
    prior = store.prior_run("legacy-session", "legacy-request", "same")
    assert prior is not None and prior.run_id == "legacy-run"
    with pytest.raises(ValueError):
        store.prior_run("legacy-session", "legacy-request", "same", operation="resume")


def test_public_branch_isolated_idempotent_and_inherits_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "web.sqlite"
    app = create_app(workspace=workspace, database=database, model=DemoModel())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client)
        sid = session(client)
        run = client.post(
            f"/api/sessions/{sid}/runs",
            headers=HEADERS,
            json={"text": "你好", "request_id": "first-request"},
        ).json()
        assert wait_run(client, run["run_id"]) == "completed"
        original = client.get(f"/api/sessions/{sid}").json()
        checkpoints = client.get(f"/api/sessions/{sid}/checkpoints").json()
        assert len(checkpoints) == 1
        action = {"checkpoint_id": checkpoints[0]["checkpoint_id"], "request_id": "fork-request"}
        response = client.post(f"/api/sessions/{sid}/branches", headers=HEADERS, json=action)
        assert response.status_code == 201, response.text
        branch = response.json()
        bid = branch["session_id"]
        assert bid != sid and branch["workspace"] == str(workspace.resolve())
        assert (
            client.post(f"/api/sessions/{sid}/branches", headers=HEADERS, json=action).json()[
                "session_id"
            ]
            == bid
        )
        view = client.get(f"/api/sessions/{bid}").json()
        assert view["run"] is None and not view["needs_recovery"]
        assert view["history"]["messages"] == original["history"]["messages"]
        run = client.post(
            f"/api/sessions/{bid}/runs",
            headers=HEADERS,
            json={"text": "hello", "request_id": "branch-request"},
        ).json()
        assert wait_run(client, run["run_id"]) == "completed"
        assert len(client.get(f"/api/sessions/{bid}").json()["history"]["messages"]) == 4
        assert client.get(f"/api/sessions/{sid}").json()["history"] == original["history"]
        missing = client.post(
            f"/api/sessions/{sid}/branches",
            headers=HEADERS,
            json={**action, "checkpoint_id": "missing"},
        )
        assert missing.status_code == 409  # Same request, conflicting checkpoint.
        missing = client.post(
            f"/api/sessions/{sid}/branches",
            headers=HEADERS,
            json={**action, "request_id": "missing-request", "checkpoint_id": "missing"},
        )
        assert missing.status_code == 404
        client.patch(f"/api/sessions/{sid}", headers=HEADERS, json={"archived": True})
        assert (
            client.post(f"/api/sessions/{sid}/branches", headers=HEADERS, json=action).status_code
            == 409
        )
    reopened = create_app(workspace=workspace, database=database, model=DemoModel())
    with TestClient(reopened, base_url="http://127.0.0.1") as client:
        login(client)
        client.patch(f"/api/sessions/{sid}", headers=HEADERS, json={"archived": False})
        assert (
            client.post(f"/api/sessions/{sid}/branches", headers=HEADERS, json=action).json()[
                "session_id"
            ]
            == bid
        )


def test_pending_busy_and_archived_checkpoint_actions_rejected(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        model = ControlledModel()
        bench = Workbench(database=tmp_path / "web.sqlite", workspace=workspace, model=model)
        sid = bench.store.create("busy-session").session_id
        run = await bench.start(sid, NewRun(text="hello", request_id="start-request"))
        await model.started.wait()
        checkpoint = project_history(await bench.state(sid)).checkpoint_id
        assert checkpoint is not None
        action = CheckpointAction(checkpoint_id=checkpoint, request_id="action-request")
        with pytest.raises(WebError):
            await bench.start(sid, action)
        with pytest.raises(WebError):
            await bench.fork(sid, action)
        await bench.cancel(run.run_id)
        with pytest.raises(WebError, match="已完成"):
            await bench.fork(sid, action)
        bench.store.edit(sid, SessionEdit(archived=True))
        with pytest.raises(WebError, match="归档"):
            await bench.start(sid, action)
        await bench.close()

    asyncio.run(scenario())


class RetryStreamModel(ControlledModel):
    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        try:
            if self.calls == 1:
                yield AIMessageChunk(content="discard this")
                raise ModelProviderError("provider_call_failed", "HTTPStatusError", status_code=503)
            yield AIMessageChunk(content="replacement")
        finally:
            self.closed += 1


def test_stream_retry_never_commits_partial_text(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        model = RetryStreamModel()
        bench = Workbench(database=tmp_path / "web.sqlite", workspace=workspace, model=model)
        sid = bench.store.create("retry-session").session_id
        await bench.start(sid, NewRun(text="hello", request_id="retry-request"))
        await asyncio.gather(*bench.tasks.values())
        view = await bench.view(sid)
        assert view.run is not None and view.run.status == "completed"
        assert [m.text for m in view.history.messages] == ["hello", "replacement"]
        assert model.calls == model.closed == 2 and view.preview is None
        await bench.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("malformed", [False, True])
def test_compatible_http_sse_completes_real_read_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformed: bool,
) -> None:
    requests: list[dict[str, Any]] = []
    original_client = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        requests.append(wire)
        assert wire["stream"] is True and wire["tools"]
        deltas: list[dict[str, Any]]
        if len(requests) == 1:
            deltas = [
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "read-probe",
                            "function": {
                                "name": "read",
                                "arguments": '{"path":"',
                            },
                        }
                    ]
                },
                {"tool_calls": [{"index": 0, "function": {"arguments": 'probe.txt"}'}}]},
            ]
            if malformed:
                deltas = deltas[:1]
        else:
            assert wire["messages"][-1]["role"] == "tool"
            assert "NATIVE-SSE-PROBE" in wire["messages"][-1]["content"]
            deltas = [{"content": "native "}, {"content": "stream complete"}]
        body = (
            "".join(
                "data: " + json.dumps({"choices": [{"delta": delta}]}) + "\n\n" for delta in deltas
            )
            + "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})

    def create_client(**kwargs: Any) -> httpx.AsyncClient:
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", create_client)

    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "probe.txt").write_text("NATIVE-SSE-PROBE", encoding="utf-8")
        config = resolve_model_config(
            ModelOptions(provider="compatible"),
            {
                "PI_AGENT_MODEL": "offline-test-model",
                "PI_AGENT_BASE_URL": "https://model.invalid/v1",
                "PI_AGENT_API_KEY": "synthetic-test-key",
            },
        )
        model = CompatibleAsyncChatModel(CompatibleHttpClient(config))
        bench = Workbench(database=tmp_path / "web.sqlite", workspace=workspace, model=model)
        sid = bench.store.create("native-session").session_id
        try:
            await bench.start(sid, NewRun(text="read probe.txt", request_id="native-request"))
            await asyncio.gather(*bench.tasks.values())
            view = await bench.view(sid)
            if malformed:
                assert view.run is not None and view.run.status == "failed"
                assert len(requests) == 1
                assert [item.role for item in view.history.messages] == ["user"]
                assert not any(event.phase == "after_tool" for event in view.activities)
                return
            assert view.run is not None and view.run.status == "completed"
            assert len(requests) == 2
            assert [item.role for item in view.history.messages] == [
                "user",
                "assistant",
                "tool",
                "assistant",
            ]
            assert view.history.messages[-1].text == "native stream complete"
            assert len([event for event in view.activities if event.phase == "after_tool"]) == 1
        finally:
            await bench.close()
            await model.aclose()

    asyncio.run(scenario())
