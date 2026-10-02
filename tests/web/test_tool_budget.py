"""Quotas precede execution and survive approvals, restart and checkpoint replay."""

import asyncio
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from tests.web.test_coding import begin, decision, local_client, make_app, wait_run
from tests.web.test_workbench import HEADERS, login, session

from pi_agent.tools.approval_store import ApprovalStore
from pi_agent.web.app import create_app
from pi_agent.web.schemas import (
    ALL_TOOL_NAMES,
    DEFAULT_TOOL_CALL_LIMITS,
    CheckpointAction,
    NewRun,
    SessionEdit,
)
from pi_agent.web.service import Workbench
from pi_agent.web.store import WebStore
from pi_agent.web.tool_budget import initialize_tool_budgets, open_tool_budget


def set_limits(client: Any, **limits: int) -> None:
    config = client.get("/api/bootstrap", headers=HEADERS).json()
    response = client.put(
        "/api/settings",
        headers=HEADERS,
        json={
            "workspace": config["workspace"],
            "tools": config["capabilities"],
            "tool_limits": {**config["tool_limits"], **limits},
        },
    )
    assert response.status_code == 200, response.text


def calls_for(name: str) -> list[dict[str, Any]]:
    all_args: dict[str, dict[str, Any]] = {
        "read": {"path": "file.txt"},
        "list": {"path": "."},
        "search": {"query": "first"},
        "write": {"path": "written.txt", "content": "first"},
        "edit": {"path": "file.txt", "old_text": "first", "new_text": "second"},
        "propose_command": {
            "executable": sys.executable,
            "argv": [
                "-c",
                "from pathlib import Path; p=Path('count.txt'); "
                "p.write_text(p.read_text()+'x' if p.exists() else 'x')",
            ],
            "timeout_seconds": 5,
        },
    }
    args = all_args[name]
    return [{"name": name, "args": args, "id": f"call-{i}"} for i in range(2)]


def tool_results(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [message for message in view["history"]["messages"] if message["role"] == "tool"]


@pytest.mark.parametrize("name", ALL_TOOL_NAMES)
def test_each_tool_is_capped_before_direct_execution(tmp_path: Path, name: str) -> None:
    app = make_app(
        tmp_path,
        calls_for(name),
        require_approval=False,
        allowed_executables=frozenset({sys.executable}),
    )
    (tmp_path / "workspace/file.txt").write_text("first")
    with local_client(app) as client:
        login(client)
        assert client.get("/api/bootstrap", headers=HEADERS).json()["tool_limits"] == {
            tool: 20 for tool in ALL_TOOL_NAMES
        }
        set_limits(client, **{name: 1})
        view = begin(client, session(client))
        results = tool_results(view)
        assert len(results) == 2
        assert "tool_call_limit" not in results[0]["text"]
        assert json.loads(results[1]["text"])["code"] == "tool_call_limit"
        assert view["run"]["status"] == "completed"
        if name == "propose_command":
            assert (tmp_path / "workspace/count.txt").read_text() == "x"
        if name in {"write", "edit", "propose_command"}:
            assert len(view["proposals"]) == 1


@pytest.mark.parametrize("name", ["write", "edit", "propose_command"])
def test_zero_coding_limit_creates_no_proposal_or_effect(tmp_path: Path, name: str) -> None:
    app = make_app(tmp_path, calls_for(name), allowed_executables=frozenset({sys.executable}))
    target = tmp_path / "workspace/file.txt"
    target.write_text("first")
    with local_client(app) as client:
        login(client)
        set_limits(client, **{name: 0})
        view = begin(client, session(client))
        assert not view["proposals"] and not view["awaiting_approval"]
        assert all(json.loads(m["text"])["code"] == "tool_call_limit" for m in tool_results(view))
        assert target.read_text() == "first"
        assert not (target.parent / "written.txt").exists()
        assert not (target.parent / "count.txt").exists()


@pytest.mark.parametrize("choice", ["approve", "reject"])
def test_restart_and_approval_keep_original_quota_and_new_turn_resets(
    tmp_path: Path, choice: str
) -> None:
    calls = calls_for("write")
    with local_client(make_app(tmp_path, calls)) as client:
        login(client)
        set_limits(client, write=1)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        set_limits(client, write=20)
    with local_client(make_app(tmp_path, calls)) as client:
        login(client)
        response = decision(client, sid, proposal, choice)
        assert response.status_code == 202
        assert wait_run(client, response.json()["run_id"])["status"] == "completed"
        view = client.get(f"/api/sessions/{sid}").json()
        assert len(view["proposals"]) == 1
        assert json.loads(tool_results(view)[1]["text"])["code"] == "tool_call_limit"
        assert (tmp_path / "workspace/written.txt").exists() == (choice == "approve")
        # A new user message snapshots the updated cap, with no inherited usage.
        (tmp_path / "workspace/written.txt").unlink(missing_ok=True)
        later = begin(client, sid, "new-turn")
        assert later["awaiting_approval"]
        fresh = next(p for p in later["proposals"] if p["status"] == "pending")
        response = decision(client, sid, fresh, "reject", "second-decision")
        wait_run(client, response.json()["run_id"])
        final = client.get(f"/api/sessions/{sid}").json()
        assert final["awaiting_approval"]  # Second call also has an available slot.


def test_failed_attempt_consumes_a_slot(tmp_path: Path) -> None:
    calls = calls_for("read")
    calls[0]["args"] = {"path": "missing.txt"}
    with local_client(make_app(tmp_path, calls)) as client:
        login(client)
        set_limits(client, read=1)
        results = tool_results(begin(client, session(client)))
        assert json.loads(results[0]["text"])["code"] != "tool_call_limit"
        assert json.loads(results[1]["text"])["code"] == "tool_call_limit"


class RepeatedReadModel:
    def __init__(self, attempts: int, *, pause: bool = False) -> None:
        self.attempts = attempts
        self.pause = pause
        self.entered = asyncio.Event()

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        last_user = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        completed = sum(isinstance(m, ToolMessage) for m in messages[last_user + 1 :])
        if completed == 1 and self.pause:
            self.entered.set()
            await asyncio.Event().wait()
        if completed >= self.attempts:
            return AIMessage(content="done")
        return AIMessage(
            content="",
            tool_calls=[{"name": "read", "args": {"path": "file.txt"}, "id": f"read-{completed}"}],
        )


def test_default_twenty_limit_is_shared_across_model_rounds(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "file.txt").write_text("readable")
    app = create_app(
        workspace=workspace, database=tmp_path / "db.sqlite", model=RepeatedReadModel(21)
    )
    with local_client(app) as client:
        login(client)
        sid = session(client)
        view = begin(client, sid)
        before = view["history"]["next_before"]
        assert before is not None
        older = client.get(
            f"/api/sessions/{sid}/messages",
            params={"before": before, "checkpoint": view["history"]["checkpoint_id"]},
        ).json()
        results = tool_results(
            {"history": {"messages": older["messages"] + view["history"]["messages"]}}
        )
        assert len(results) == 21
        assert all(m["text"] == "readable" for m in results[:20])
        assert json.loads(results[20]["text"])["code"] == "tool_call_limit"


def test_cancel_restart_and_explicit_resume_reuse_the_turn_budget(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "file.txt").write_text("readable")
        database = tmp_path / "db.sqlite"
        model = RepeatedReadModel(2, pause=True)
        bench = Workbench(database=database, workspace=workspace, model=model)
        bench.tool_call_limits = {**DEFAULT_TOOL_CALL_LIMITS, "read": 1}
        sid = bench.store.create("resume-budget").session_id
        run = await bench.start(sid, NewRun(text="read", request_id="initial-request"))
        await asyncio.wait_for(model.entered.wait(), 3)
        assert (await bench.cancel(run.run_id)).status == "cancelled"
        view = await bench.view(sid)
        assert view.needs_recovery and view.history.checkpoint_id
        await bench.close()
        reopened = Workbench(database=database, workspace=workspace, model=RepeatedReadModel(2))
        assert reopened.tool_call_limits["read"] == 20
        action = CheckpointAction(
            checkpoint_id=view.history.checkpoint_id, request_id="resume-request"
        )
        await reopened.start(sid, action)
        await asyncio.gather(*reopened.tasks.values())
        final = await reopened.view(sid)
        results = [m for m in final.history.messages if m.role == "tool"]
        assert len(results) == 2 and results[0].text == "readable"
        assert json.loads(results[1].text)["code"] == "tool_call_limit"
        assert sum(m.role == "user" for m in final.history.messages) == 1
        assert final.run is not None and final.run.status == "completed"
        await reopened.close()

    asyncio.run(scenario())


def test_budget_reservations_are_atomic_idempotent_and_session_scoped(tmp_path: Path) -> None:
    store = WebStore(tmp_path / "db.sqlite")
    initialize_tool_budgets(store)
    budget = open_tool_budget(store, "one", "turn", {"write": 1}, ("write",))

    def reserve(i: int) -> bool:
        return budget.reserve(message_id="model", tool_call_id=str(i), tool_name="write")

    with ThreadPoolExecutor(max_workers=4) as pool:
        granted = list(pool.map(reserve, range(12)))
    assert sum(granted) == 1
    assert [reserve(i) for i in range(12)] == granted
    reopened = open_tool_budget(store, "one", "turn", {"write": 20}, ())
    assert reopened.limits == {"write": 1} and reopened.tools == ("write",)
    assert not reopened.reserve(message_id="next", tool_call_id="other", tool_name="write")
    other = open_tool_budget(store, "two", "turn", {"write": 1}, ("write",))
    assert other.reserve(message_id="model", tool_call_id="0", tool_name="write")
    with pytest.raises(ValueError, match="identity changed"):
        budget.reserve(message_id="model", tool_call_id="0", tool_name="edit")


def test_saved_readonly_limits_migrate_without_resetting_values(tmp_path: Path) -> None:
    store = WebStore(tmp_path / "db.sqlite")
    store.save_settings(str(tmp_path), ("read",), {"read": 0, "list": 7, "search": 4})
    for _ in range(2):
        saved = WebStore(store.database).settings()
        assert saved is not None
        assert saved[1] == ("read",)
        assert saved[2] == {**DEFAULT_TOOL_CALL_LIMITS, "read": 0, "list": 7, "search": 4}


def test_unmarked_history_does_not_gain_workspace_provenance_when_edited(tmp_path: Path) -> None:
    store = WebStore(tmp_path / "db.sqlite", tmp_path)
    store.catalog.record_session("legacy")
    store.create("known", tmp_path)
    for edit in (
        SessionEdit(title="renamed"),
        SessionEdit(archived=True),
        SessionEdit(archived=False),
    ):
        store.edit("legacy", edit)
        item = store.session("legacy")
        assert item is not None and not item.workspace_known
        assert item.workspace == str(tmp_path.resolve())
    assert {s.session_id: s.workspace_known for s in store.sessions()} == {
        "legacy": False,
        "known": True,
    }


def test_pre_upgrade_checkpoint_seeds_attempts_up_to_pending_approval(tmp_path: Path) -> None:
    store = WebStore(tmp_path / "db.sqlite")
    initialize_tool_budgets(store)
    approvals = ApprovalStore(store.database)
    # Only the prefix through the pending proposal was executed before the interrupt.
    calls = calls_for("write")
    proposal = approvals.prepare(
        session="old",
        workspace=str(tmp_path),
        message="ai",
        call="call-0",
        kind="file",
        payload={"operation": "write"},
    )
    messages: list[AnyMessage] = [
        HumanMessage(content="old request", id="turn"),
        AIMessage(content="", id="ai", tool_calls=calls),
    ]
    budget = open_tool_budget(
        store, "old", "turn", {"write": 1}, ("write",), history=messages, proposals=[proposal]
    )
    assert budget.reserve(message_id="ai", tool_call_id="call-0", tool_name="write")
    assert not budget.reserve(message_id="ai", tool_call_id="call-1", tool_name="write")
    # An old error for exceeding the cap is not an execution reservation.
    completed: list[AnyMessage] = [
        HumanMessage(content="request", id="t"),
        AIMessage(content="", id="m", tool_calls=calls),
        ToolMessage(content='{"code":"tool_call_limit"}', status="error", tool_call_id="call-0"),
    ]
    other = open_tool_budget(store, "old", "t", {"write": 1}, ("write",), history=completed)
    assert not other.reserve(message_id="m", tool_call_id="call-0", tool_name="write")
    assert other.reserve(message_id="m", tool_call_id="call-1", tool_name="write")
