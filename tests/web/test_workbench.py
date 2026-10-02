"""Public HTTP contracts exercised against the actual graph and SQLite."""

import asyncio
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from pi_agent.web.app import create_app
from pi_agent.web.demo import DemoModel
from pi_agent.web.schemas import NewRun
from pi_agent.web.service import Workbench

HEADERS = {"X-Pi-Request": "1"}


def database_outside(workspace: Path) -> Path:
    return workspace.parent / f"{workspace.name}-web.sqlite"


def test_web_database_cannot_be_inside_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the workspace"):
        create_app(workspace=tmp_path, database=tmp_path / "web.sqlite", model=DemoModel())
    assert not (tmp_path / "web.sqlite").exists()


def test_demo_model_answers_greeting_without_calling_tools() -> None:
    reply = asyncio.run(DemoModel().ainvoke((HumanMessage(content="你好"),)))

    assert isinstance(reply.content, str)
    assert reply.content.startswith("你好")
    assert reply.tool_calls == []


def test_demo_model_does_not_scan_workspace_for_general_question() -> None:
    reply = asyncio.run(DemoModel().ainvoke((HumanMessage(content="什么是 LangGraph?"),)))

    assert isinstance(reply.content, str)
    assert "离线演示模式" in reply.content
    assert reply.tool_calls == []


def login(client: TestClient) -> None:
    assert client.get("/api/bootstrap", headers=HEADERS).status_code == 200


def session(client: TestClient) -> str:
    response = client.post("/api/sessions", headers=HEADERS)
    assert response.status_code == 201
    return str(response.json()["session_id"])


def send(client: TestClient, session_id: str, request_id: str = "request-001") -> str:
    response = client.post(
        f"/api/sessions/{session_id}/runs",
        headers=HEADERS,
        json={"text": "读取 probe.txt", "request_id": request_id},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["run_id"])


def wait_run(client: TestClient, run_id: str) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = client.get(f"/api/runs/{run_id}").json()["status"]
        if state != "running":
            return str(state)
        time.sleep(0.02)
    pytest.fail("Run did not finish within test deadline.")


def test_read_persistence_idempotency_and_session_management(tmp_path: Path) -> None:
    (tmp_path / "probe.txt").write_text("web probe ready", encoding="utf-8")
    database = database_outside(tmp_path)
    app = create_app(workspace=tmp_path, database=database, model=DemoModel())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client)
        sid = session(client)
        run_id = send(client, sid)
        assert send(client, sid) == run_id
        assert wait_run(client, run_id) == "completed"
        view = client.get(f"/api/sessions/{sid}").json()
        assert any(
            m["role"] == "tool" and "web probe ready" in m["text"]
            for m in view["history"]["messages"]
        )
        assert any(
            e["phase"] == "after_tool" and e["tool_name"] == "read" for e in view["activities"]
        )
        tool_event = next(
            e for e in view["activities"] if e["phase"] == "after_tool" and e["tool_name"] == "read"
        )
        detail = client.get(f"/api/sessions/{sid}/activities/{tool_event['event_id']}")
        assert detail.status_code == 200, detail.text
        projection = detail.json()
        assert projection["node"] == "tools"
        assert any("web probe ready" in item["text"] for item in projection["output"])
        assert projection["snapshot_after"]["messages"]
        assert "system prompt" not in detail.text.lower()
        assert len([e for e in view["activities"] if e["phase"] == "run_end"]) == 1
        assert send(client, sid) == run_id
        conflict = client.post(
            f"/api/sessions/{sid}/runs",
            headers=HEADERS,
            json={"text": "different", "request_id": "request-001"},
        )
        assert conflict.status_code == 409
        assert (
            client.patch(
                f"/api/sessions/{sid}",
                headers=HEADERS,
                json={"title": "My project", "archived": True},
            ).status_code
            == 200
        )
        assert client.get("/api/sessions").json() == []
        assert client.get("/api/sessions?archived=true").json()[0]["title"] == "My project"
        assert (
            client.patch(
                f"/api/sessions/{sid}", headers=HEADERS, json={"archived": False}
            ).status_code
            == 200
        )
        original_epoch = view["server_epoch"]
    reopened = create_app(workspace=tmp_path, database=database, model=DemoModel())
    with TestClient(reopened, base_url="http://127.0.0.1") as client:
        login(client)
        view = client.get(f"/api/sessions/{sid}").json()
        assert view["server_epoch"] != original_epoch
        assert view["history"]["messages"][-1]["role"] == "assistant"
        assert send(client, sid) == run_id
        assert wait_run(client, send(client, sid, "request-002")) == "completed"


def test_http_auth_origin_validation_and_safe_errors(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path, database=database_outside(tmp_path), model=DemoModel())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/sessions").status_code == 401
        assert client.get("/api/bootstrap").status_code == 403
        assert (
            client.get(
                "/api/bootstrap", headers={**HEADERS, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.get("/api/bootstrap", headers={**HEADERS, "Host": "evil.test"}).status_code
            == 400
        )
        login(client)
        assert client.post("/api/sessions").status_code == 403
        assert (
            client.post(
                "/api/sessions", headers={**HEADERS, "Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 403
        )
        sid = session(client)
        response = client.post(
            f"/api/sessions/{sid}/runs",
            headers=HEADERS,
            json={"text": "credential-do-not-echo", "request_id": "x", "workspace": "C:/"},
        )
        assert response.status_code == 422
        assert "credential-do-not-echo" not in response.text
        assert client.get("/api/sessions/not-found").status_code == 404
        assert (
            client.post("/api/sessions", headers=HEADERS, content="x" * 300000).status_code == 413
        )
        assert (
            client.post(
                "/api/sessions", headers={**HEADERS, "Content-Length": "invalid"}
            ).status_code
            == 400
        )
        config = client.get("/api/bootstrap", headers=HEADERS)
        assert "api_key" not in config.text
        assert "HttpOnly" in config.headers["set-cookie"]


def test_workspace_and_tool_settings_are_validated_saved_and_session_scoped(tmp_path: Path) -> None:
    original_workspace = tmp_path / "original"
    alternate_workspace = tmp_path / "alternate"
    original_workspace.mkdir()
    alternate_workspace.mkdir()
    database = tmp_path / "test.sqlite"
    app = create_app(workspace=original_workspace, database=database, model=DemoModel())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client)
        original = session(client)
        changed = client.put(
            "/api/settings",
            headers=HEADERS,
            json={
                "workspace": str(alternate_workspace),
                "tools": ["read", "search"],
                "tool_limits": {"read": 7, "list": 4, "search": 2},
            },
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["workspace"] == str(alternate_workspace.resolve())
        assert changed.json()["capabilities"] == ["read", "search"]
        assert changed.json()["tool_limits"] == {
            "read": 7,
            "list": 4,
            "search": 2,
            "write": 20,
            "edit": 20,
            "propose_command": 20,
        }
        assert client.get(f"/api/sessions/{original}").json()["session"]["workspace"] == str(
            original_workspace.resolve()
        )
        fresh = session(client)
        assert client.get(f"/api/sessions/{fresh}").json()["session"]["workspace"] == str(
            alternate_workspace.resolve()
        )
        invalid = client.put(
            "/api/settings",
            headers=HEADERS,
            json={"workspace": str(tmp_path / "missing"), "tools": ["write"]},
        )
        assert invalid.status_code == 422
        invalid_limit = client.put(
            "/api/settings",
            headers=HEADERS,
            json={
                "workspace": str(alternate_workspace),
                "tools": ["read"],
                "tool_limits": {"read": 21, "list": 4, "search": 4},
            },
        )
        assert invalid_limit.status_code == 422
        containing_database = client.put(
            "/api/settings",
            headers=HEADERS,
            json={
                "workspace": str(tmp_path),
                "tools": ["read"],
                "tool_limits": {"read": 4, "list": 4, "search": 4},
            },
        )
        assert containing_database.status_code == 422
        assert client.get("/api/bootstrap", headers=HEADERS).json()["workspace"] == str(
            alternate_workspace.resolve()
        )

    reopened = create_app(workspace=original_workspace, database=database, model=DemoModel())
    with TestClient(reopened, base_url="http://127.0.0.1") as client:
        login(client)
        saved = client.get("/api/bootstrap", headers=HEADERS).json()
        assert saved["workspace"] == str(alternate_workspace.resolve())
        assert saved["capabilities"] == ["read", "search"]
        assert saved["tool_limits"] == {
            "read": 7,
            "list": 4,
            "search": 2,
            "write": 20,
            "edit": 20,
            "propose_command": 20,
        }


class SlowModel:
    calls = 0

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        del messages, config
        self.calls += 1
        await asyncio.sleep(30)
        return AIMessage(content="late")


class PromptCaptureModel:
    def __init__(self) -> None:
        self.calls: list[tuple[AnyMessage, ...]] = []

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        del config
        self.calls.append(tuple(messages))
        return AIMessage(content="你好!")


def test_workbench_uses_builtin_prompt_and_only_pi_workspace_rules(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Codex-only instruction", encoding="utf-8")
    (tmp_path / "PI-AGENTS.md").write_text("Pi-only instruction", encoding="utf-8")
    model = PromptCaptureModel()

    async def scenario() -> None:
        workbench = Workbench(database=database_outside(tmp_path), workspace=tmp_path, model=model)
        session_id = workbench.store.create("prompt test").session_id
        run = await workbench.start(session_id, NewRun(text="你好", request_id="prompt-request"))
        await asyncio.gather(*workbench.tasks.values())
        record = workbench.store.run(run.run_id)
        assert record is not None and record.status == "completed"
        await workbench.close()

    asyncio.run(scenario())

    prompt = str(model.calls[0][0].content)
    assert "You are Pi, a helpful local workspace assistant." in prompt
    assert "Greetings, thanks, and general questions do not require workspace tools" in prompt
    assert "Pi-only instruction" in prompt
    assert "Codex-only instruction" not in prompt


def test_cancel_precise_run_busy_and_shutdown(tmp_path: Path) -> None:
    model = SlowModel()
    app = create_app(workspace=tmp_path, database=database_outside(tmp_path), model=model)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client)
        sid = session(client)
        run_id = send(client, sid)
        conflict = client.post(
            f"/api/sessions/{sid}/runs",
            headers=HEADERS,
            json={"text": "hello", "request_id": "other-request"},
        )
        assert conflict.status_code == 409
        assert client.post("/api/runs/wrong-run/cancel", headers=HEADERS).status_code == 404
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "running"
        assert client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).status_code == 200
        assert wait_run(client, run_id) == "cancelled"
        assert (
            client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).json()["status"]
            == "cancelled"
        )
        sid2 = session(client)
        active = send(client, sid2)
    # Lifespan shutdown owns and joins the second task.
    run = app.state.workbench.store.run(active)
    assert run.status == "cancelled"
    assert not app.state.workbench.tasks


def test_completed_run_is_not_relabelled_cancelled(tmp_path: Path) -> None:
    app = create_app(workspace=tmp_path, database=database_outside(tmp_path), model=DemoModel())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client)
        run_id = send(client, session(client))
        assert wait_run(client, run_id) == "completed"
        assert (
            client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).json()["status"]
            == "completed"
        )


def test_browser_request_cancellation_does_not_own_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        workbench = Workbench(
            database=database_outside(tmp_path), workspace=tmp_path, model=DemoModel()
        )
        sid = workbench.store.create("session").session_id
        run = await workbench.start(sid, NewRun(text="list files", request_id="browser-request"))
        # No subscriber or request task remains. The application still completes the run.
        await asyncio.gather(*workbench.tasks.values())
        record = workbench.store.run(run.run_id)
        assert record is not None and record.status == "completed"
        await workbench.close()

    asyncio.run(scenario())


def test_restart_marks_unfinished_receipt_without_replay(tmp_path: Path) -> None:
    database = database_outside(tmp_path)
    model = SlowModel()
    app = create_app(workspace=tmp_path, database=database, model=model)
    store = app.state.workbench.store
    store.create("old-session")
    store.add_run("old-session", "old-run", "old-request", "never replay")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        login(client)
        assert client.get("/api/runs/old-run").json()["status"] == "needs_recovery"
        duplicate = client.post(
            "/api/sessions/old-session/runs",
            headers=HEADERS,
            json={"text": "never replay", "request_id": "old-request"},
        )
        assert duplicate.json()["run_id"] == "old-run"
        assert model.calls == 0
