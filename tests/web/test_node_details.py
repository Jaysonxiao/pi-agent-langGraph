"""Activity details address a graph checkpoint, rather than a run event ordinal."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from tests.web.test_coding import begin, decision, local_client, make_app, wait_run
from tests.web.test_continuation import ControlledModel
from tests.web.test_workbench import login, session

from pi_agent.web.schemas import NewRun
from pi_agent.web.service import WebError, Workbench


def after_tools(view: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in view["activities"] if a["phase"] == "after_tool"]


def detail(client: Any, sid: str, event: dict[str, Any]) -> Any:
    return client.get(f"/api/sessions/{sid}/activities/{event['event_id']}")


def test_multiple_tools_share_checkpoint_but_show_the_selected_call(tmp_path: Path) -> None:
    calls = [
        {"name": "read", "args": {"path": f"{name}.txt"}, "id": name}
        for name in ("first", "second")
    ]
    app = make_app(tmp_path, calls)
    for name in ("first", "second"):
        (tmp_path / "workspace" / f"{name}.txt").write_text(name)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        view = begin(client, sid)
        events = after_tools(view)
        assert len(events) == 2
        for event, text in zip(events, ("first", "second"), strict=True):
            response = detail(client, sid, event)
            assert response.status_code == 200, response.text
            assert [item["text"] for item in response.json()["output"]] == [text]


def test_approved_tool_detail_survives_restart_and_later_turn(tmp_path: Path) -> None:
    calls = [
        {"name": "write", "args": {"path": "new.txt", "content": "created"}, "id": "write-one"}
    ]
    with local_client(make_app(tmp_path, calls)) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        response = decision(client, sid, proposal)
        wait_run(client, response.json()["run_id"])
        event = after_tools(client.get(f"/api/sessions/{sid}").json())[0]
        response = detail(client, sid, event)
        assert response.status_code == 200, response.text
        expected = response.json()
    with local_client(make_app(tmp_path, calls)) as client:
        login(client)
        begin(client, sid, "later-turn")
        response = detail(client, sid, event)
        assert response.status_code == 200, response.text
        assert response.json() == expected


def test_partial_tool_batch_waits_for_remaining_approval(tmp_path: Path) -> None:
    calls = [
        {"name": "read", "args": {"path": "file.txt"}, "id": "read-one"},
        {"name": "write", "args": {"path": "new.txt", "content": "created"}, "id": "write-one"},
    ]
    app = make_app(tmp_path, calls)
    (tmp_path / "workspace/file.txt").write_text("read first")
    with local_client(app) as client:
        login(client)
        sid = session(client)
        view = begin(client, sid)
        event = after_tools(view)[0]
        response = detail(client, sid, event)
        assert response.status_code == 409
        assert "整批" in response.json()["detail"]
        response = decision(client, sid, view["proposals"][0])
        wait_run(client, response.json()["run_id"])
        response = detail(client, sid, event)
        assert response.status_code == 200, response.text
        assert [item["text"] for item in response.json()["output"]] == ["read first"]


def test_legacy_activity_links_by_task_time_even_after_approval_resume(tmp_path: Path) -> None:
    calls = [
        {"name": "write", "args": {"path": "legacy.txt", "content": "created"}, "id": "write-one"}
    ]
    app = make_app(tmp_path, calls)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        response = decision(client, sid, begin(client, sid)["proposals"][0])
        wait_run(client, response.json()["run_id"])
        event = after_tools(client.get(f"/api/sessions/{sid}").json())[0]
        before = detail(client, sid, event).json()
        with app.state.workbench.store.connect() as db:
            db.execute(
                "UPDATE web_activity SET checkpoint_id=NULL,tool_call_id=NULL WHERE event_id=?",
                (event["event_id"],),
            )
        response = detail(client, sid, event)
        assert response.status_code == 200, response.text
        assert response.json() == before


def test_checkpoint_identity_is_scoped_to_the_activity_session(tmp_path: Path) -> None:
    app = make_app(tmp_path, [{"name": "list", "args": {}, "id": "list-one"}])
    with local_client(app) as client:
        login(client)
        first = session(client)
        second = session(client)
        event = after_tools(begin(client, first))[0]
        other = after_tools(begin(client, second))[0]
        with app.state.workbench.store.connect() as db:
            db.execute(
                "UPDATE web_activity SET checkpoint_id=? WHERE event_id=?",
                (other["checkpoint_id"], event["event_id"]),
            )
        assert detail(client, first, event).status_code == 404
        assert detail(client, second, event).status_code == 404


def test_cancelled_model_has_no_committed_detail(tmp_path: Path) -> None:
    async def scenario() -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        model = ControlledModel()
        bench = Workbench(database=tmp_path / "db.sqlite", workspace=workspace, model=model)
        sid = bench.store.create("cancel-node").session_id
        run = await bench.start(sid, NewRun(text="hello", request_id="cancel-request"))
        await asyncio.wait_for(model.started.wait(), 3)
        await bench.cancel(run.run_id)
        event = next(e for e in bench.store.events(sid) if e.phase == "after_model")
        assert event.outcome == "cancelled"
        with pytest.raises(WebError, match="取消") as error:
            await bench.activity_detail(sid, event.event_id)
        assert error.value.status == 409
        await bench.close()

    asyncio.run(scenario())
