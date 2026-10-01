"""Default capabilities, durable automatic execution, and next-turn selections."""

import asyncio
import json
import sqlite3
import sys
import threading
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from tests.web.test_coding import begin, decision, local_client, make_app, wait_run
from tests.web.test_workbench import HEADERS, login, session

from pi_agent.web.app import create_app
from pi_agent.web.demo import DemoModel
from pi_agent.web.schemas import ALL_TOOL_NAMES, DEFAULT_TOOL_CALL_LIMITS
from pi_agent.web.tool_policy import default_executables


def settings(client: Any, tools: list[str]) -> Any:
    config = client.get("/api/bootstrap", headers=HEADERS).json()
    return client.put(
        "/api/settings",
        headers=HEADERS,
        json={
            "workspace": config["workspace"],
            "tools": tools,
            "tool_limits": config["tool_limits"],
        },
    )


def write_call(path: str = "file.txt") -> dict[str, Any]:
    return {"name": "write", "args": {"path": path, "content": "first"}, "id": "write-one"}


def test_default_tools_and_approval_are_enabled(tmp_path: Path) -> None:
    with local_client(make_app(tmp_path, [write_call()])) as client:
        login(client)
        config = client.get("/api/bootstrap", headers=HEADERS).json()
        assert config["capabilities"] == list(ALL_TOOL_NAMES)
        assert config["available_tools"] == list(ALL_TOOL_NAMES)
        assert config["require_approval"] is True
        assert config["allowed_executables"] == sorted(default_executables())
        view = begin(client, session(client))
        assert view["awaiting_approval"]
        assert not (tmp_path / "workspace/file.txt").exists()


def test_automatic_multiple_tools_execute_once_and_persist_results(tmp_path: Path) -> None:
    calls = [
        write_call(),
        {
            "name": "edit",
            "args": {"path": "file.txt", "old_text": "first", "new_text": "second"},
            "id": "edit-one",
        },
        {
            "name": "propose_command",
            "args": {
                "executable": sys.executable,
                "argv": [
                    "-c",
                    "from pathlib import Path; p=Path('count.txt'); "
                    "p.write_text(p.read_text()+'x' if p.exists() else 'x'); print('ran')",
                ],
                "timeout_seconds": 5,
            },
            "id": "command-one",
        },
    ]
    with local_client(
        make_app(
            tmp_path, calls, require_approval=False, allowed_executables=frozenset({sys.executable})
        )
    ) as client:
        login(client)
        sid = session(client)
        first = begin(client, sid)
        assert first["run"]["status"] == "completed" and not first["awaiting_approval"]
        assert (tmp_path / "workspace/file.txt").read_text() == "second"
        assert (tmp_path / "workspace/count.txt").read_text() == "x"
        assert all(
            p["status"] == "completed" and not p["requires_approval"] for p in first["proposals"]
        )
        assert len([m for m in first["history"]["messages"] if m["role"] == "tool"]) == 3
        assert begin(client, sid)["run"]["run_id"] == first["run"]["run_id"]
    with local_client(
        make_app(
            tmp_path, calls, require_approval=False, allowed_executables=frozenset({sys.executable})
        )
    ) as client:
        login(client)
        assert begin(client, sid)["run"]["run_id"] == first["run"]["run_id"]
        assert (tmp_path / "workspace/count.txt").read_text() == "x"


def test_restart_without_approval_does_not_consume_old_pending_proposal(tmp_path: Path) -> None:
    with local_client(make_app(tmp_path, [write_call()])) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
    with local_client(make_app(tmp_path, [write_call()], require_approval=False)) as client:
        login(client)
        assert client.get(f"/api/sessions/{sid}").json()["awaiting_approval"]
        assert not (tmp_path / "workspace/file.txt").exists()
        response = decision(client, sid, proposal)
        assert response.status_code == 202
        assert wait_run(client, response.json()["run_id"])["status"] == "completed"
        assert (tmp_path / "workspace/file.txt").read_text() == "first"


@pytest.mark.parametrize("name", ["write", "edit", "propose_command"])
def test_deselected_coding_tool_cannot_execute_forced_model_call(tmp_path: Path, name: str) -> None:
    calls: dict[str, dict[str, Any]] = {
        "write": write_call(),
        "edit": {
            "name": "edit",
            "args": {"path": "file.txt", "old_text": "first", "new_text": "bad"},
            "id": "edit-one",
        },
        "propose_command": {
            "name": "propose_command",
            "args": {
                "executable": sys.executable,
                "argv": ["-c", "from pathlib import Path; Path('ran').touch()"],
                "timeout_seconds": 5,
            },
            "id": "command-one",
        },
    }
    app = make_app(
        tmp_path,
        [calls[name]],
        require_approval=False,
        allowed_executables=frozenset({sys.executable}),
    )
    target = tmp_path / "workspace/file.txt"
    target.write_text("first")
    with local_client(app) as client:
        login(client)
        assert settings(client, [t for t in ALL_TOOL_NAMES if t != name]).status_code == 200
        sid = session(client)
        view = begin(client, sid)
        assert not view["proposals"] and view["run"]["status"] == "completed"
        assert any(m["role"] == "tool" for m in view["history"]["messages"])
        assert target.read_text() == "first" and not (target.parent / "ran").exists()
        assert settings(client, []).status_code == 200
    with local_client(make_app(tmp_path, [calls[name]])) as client:
        login(client)
        assert client.get("/api/bootstrap", headers=HEADERS).json()["capabilities"] == []


@pytest.mark.parametrize("has_saved_settings", [True, False])
def test_old_read_only_settings_gain_coding_defaults_only_once(
    tmp_path: Path, has_saved_settings: bool
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "CREATE TABLE web_settings (settings_id INTEGER PRIMARY KEY, workspace TEXT, "
            "tools_json TEXT, tool_limits_json TEXT)"
        )
        if has_saved_settings:
            db.execute(
                "INSERT INTO web_settings VALUES (1,?,?,?)",
                (str(workspace), '["read"]', json.dumps(DEFAULT_TOOL_CALL_LIMITS)),
            )
    initial = (
        ["read", "write", "edit", "propose_command"] if has_saved_settings else list(ALL_TOOL_NAMES)
    )
    for expected in (initial, ["read"]):
        with local_client(
            create_app(workspace=workspace, database=database, model=DemoModel())
        ) as client:
            login(client)
            assert client.get("/api/bootstrap", headers=HEADERS).json()["capabilities"] == expected
            assert settings(client, ["read"]).status_code == 200


class GatedModel:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.bound: list[list[str]] = []

    def bind_tools(self, tools: list[dict[str, Any]]) -> "GatedModel":
        self.bound.append([tool["function"]["name"] for tool in tools])
        return self

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        last_user = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        if any(isinstance(m, ToolMessage) for m in messages[last_user + 1 :]):
            return AIMessage(content="done")
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return AIMessage(content="", tool_calls=[write_call()])


def test_selection_during_run_changes_next_turn_and_model_binding(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    model = GatedModel()
    app = create_app(
        workspace=workspace, database=tmp_path / "db.sqlite", model=model, require_approval=False
    )
    with local_client(app) as client:
        login(client)
        sid = session(client)
        response = client.post(
            f"/api/sessions/{sid}/runs",
            headers=HEADERS,
            json={"text": "write", "request_id": "first-turn"},
        )
        assert response.status_code == 202
        assert model.entered.wait(timeout=5)
        try:
            assert settings(client, []).status_code == 200
        finally:
            model.release.set()
        assert wait_run(client, response.json()["run_id"])["status"] == "completed"
        assert (workspace / "file.txt").read_text() == "first"
        (workspace / "file.txt").unlink()
        assert begin(client, sid, "next-turn")["run"]["status"] == "completed"
        assert not (workspace / "file.txt").exists()
        assert model.bound[0] == list(ALL_TOOL_NAMES) and model.bound[-1] == []


def test_browser_cannot_enable_server_disabled_capability(tmp_path: Path) -> None:
    with local_client(
        make_app(tmp_path, [write_call()], file_mutations=False, allowed_executables=frozenset())
    ) as client:
        login(client)
        assert settings(client, ["write"]).status_code == 422
        assert settings(client, ["propose_command"]).status_code == 422
