"""Durable Web approvals exercise real graph interrupts, files and subprocesses."""

import sqlite3
import sys
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient
from tests.web.test_workbench import HEADERS, login, session
from tests.web.test_workbench import wait_run as wait_status

from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.command_approval import CommandApprovalStore
from pi_agent.tools.process import ProcessArguments
from pi_agent.web.app import create_app


class CodingModel:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls

    async def ainvoke(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AIMessage:
        last_user = max(
            i for i, message in enumerate(messages) if isinstance(message, HumanMessage)
        )
        if any(isinstance(message, ToolMessage) for message in messages[last_user + 1 :]):
            return AIMessage(content="审批操作已经处理。")
        return AIMessage(content="", tool_calls=self.calls)


def local_client(app: Any) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1")


def wait_run(client: TestClient, run_id: str) -> dict[str, Any]:
    wait_status(client, run_id)
    result: dict[str, Any] = client.get(f"/api/runs/{run_id}").json()
    return result


def make_app(tmp_path: Path, calls: list[dict[str, Any]], **kwargs: Any) -> Any:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return create_app(
        workspace=workspace, database=tmp_path / "web.sqlite", model=CodingModel(calls), **kwargs
    )


def begin(client: TestClient, sid: str, request: str = "coding-request") -> dict[str, Any]:
    response = client.post(
        f"/api/sessions/{sid}/runs",
        headers=HEADERS,
        json={"text": "进行审批操作", "request_id": request},
    )
    assert response.status_code == 202
    wait_run(client, response.json()["run_id"])
    result: dict[str, Any] = client.get(f"/api/sessions/{sid}").json()
    return result


def decision(
    client: TestClient,
    sid: str,
    proposal: dict[str, Any],
    value: str = "approve",
    request: str = "decision-request",
) -> Any:
    return client.post(
        f"/api/sessions/{sid}/proposals/{proposal['proposal_id']}/decision",
        headers=HEADERS,
        json={"version": proposal["version"], "decision": value, "request_id": request},
    )


def test_file_approval_survives_restart_and_is_idempotent(tmp_path: Path) -> None:
    calls = [
        {
            "name": "write",
            "args": {"path": "hello.txt", "content": "approved\r\n"},
            "id": "write-one",
        }
    ]
    with local_client(make_app(tmp_path, calls, file_mutations=True)) as client:
        login(client)
        sid = session(client)
        view = begin(client, sid)
        proposal = view["proposals"][0]
        assert view["awaiting_approval"] and not view["needs_recovery"]
        assert view["run"]["status"] == "awaiting_approval"
        assert not (tmp_path / "workspace/hello.txt").exists()
        assert "+approved" in proposal["diff"]
        assert (
            client.post(
                f"/api/sessions/{sid}/resume",
                headers=HEADERS,
                json={
                    "checkpoint_id": view["history"]["checkpoint_id"],
                    "request_id": "bypass-request",
                },
            ).status_code
            == 409
        )
    with local_client(make_app(tmp_path, calls, file_mutations=True)) as client:
        login(client)
        assert client.get(f"/api/sessions/{sid}").json()["awaiting_approval"]
        wrong = {**proposal, "version": "0" * 64}
        assert decision(client, sid, wrong).status_code == 409
        assert decision(client, session(client), proposal).status_code == 404
        response = decision(client, sid, proposal)
        assert response.status_code == 202, response.text
        run = wait_run(client, response.json()["run_id"])
        assert run["status"] == "completed"
        assert (tmp_path / "workspace/hello.txt").read_bytes() == b"approved\r\n"
        assert decision(client, sid, proposal).json()["run_id"] == run["run_id"]
        final = client.get(f"/api/sessions/{sid}").json()
        assert not final["awaiting_approval"] and not final["needs_recovery"]
        assert [message["role"] for message in final["history"]["messages"]] == [
            "user",
            "assistant",
            "tool",
            "assistant",
        ]
        # A later operation with identical parameters creates a fresh proposal.
        later = begin(client, sid, "next-operation")
        assert (
            later["proposals"][0]["proposal_id"] != proposal["proposal_id"]
            or later["run"]["status"] == "completed"
        )


@pytest.mark.parametrize("reject", [True, False])
def test_edit_rejection_and_stale_hash_never_write(tmp_path: Path, reject: bool) -> None:
    calls = [
        {
            "name": "edit",
            "args": {"path": "file.txt", "old_text": "old", "new_text": "new"},
            "id": "edit-one",
        }
    ]
    app = make_app(tmp_path, calls, file_mutations=True)
    target = tmp_path / "workspace/file.txt"
    target.write_bytes(b"old\r\n")
    target.chmod(0o755)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        if not reject:
            target.write_text("changed externally")
        response = decision(client, sid, proposal, "reject" if reject else "approve")
        assert response.status_code == 202
        wait_run(client, response.json()["run_id"])
        assert target.read_bytes() == (b"old\r\n" if reject else b"changed externally")
        status = client.get(f"/api/sessions/{sid}").json()["proposals"][0]["status"]
        assert status == ("rejected" if reject else "failed")


def test_multiple_file_calls_wait_in_order_and_preserve_mode(tmp_path: Path) -> None:
    calls = [
        {
            "name": "edit",
            "args": {"path": "file.txt", "old_text": "old", "new_text": "new"},
            "id": "first",
        },
        {"name": "write", "args": {"path": "other.txt", "content": "other"}, "id": "second"},
    ]
    app = make_app(tmp_path, calls, file_mutations=True)
    target = tmp_path / "workspace/file.txt"
    target.write_bytes(b"old\r\n")
    target.chmod(0o755)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        first = begin(client, sid)["proposals"][0]
        response = decision(client, sid, first)
        assert wait_run(client, response.json()["run_id"])["status"] == "awaiting_approval"
        assert target.read_bytes() == b"new\r\n"
        if sys.platform != "win32":
            assert target.stat().st_mode & 0o777 == 0o755
        second = client.get(f"/api/sessions/{sid}").json()["proposals"][0]
        assert second["proposal_id"] != first["proposal_id"]
        response = decision(client, sid, second, request="second-decision")
        assert response.status_code == 202, response.text
        assert wait_run(client, response.json()["run_id"])["status"] == "completed", client.get(
            f"/api/sessions/{sid}"
        ).json()
        assert (tmp_path / "workspace/other.txt").read_text() == "other"
        final = client.get(f"/api/sessions/{sid}").json()
        assert len([m for m in final["history"]["messages"] if m["role"] == "tool"]) == 2


@pytest.mark.parametrize("path", [".env", ".git/config", "secret.key", "../outside.txt"])
def test_sensitive_and_outside_paths_never_create_proposals(tmp_path: Path, path: str) -> None:
    call = {"name": "write", "args": {"path": path, "content": "data"}, "id": "bad"}
    with local_client(make_app(tmp_path, [call], file_mutations=True)) as client:
        login(client)
        sid = session(client)
        view = begin(client, sid)
        assert view["run"]["status"] == "completed" and not view["proposals"]
    assert not (tmp_path / "outside.txt").exists()


def test_claimed_file_after_crash_is_uncertain_and_never_replayed(tmp_path: Path) -> None:
    calls = [{"name": "write", "args": {"path": "uncertain.txt", "content": "data"}, "id": "one"}]
    app = make_app(tmp_path, calls, file_mutations=True)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        view = begin(client, sid)
        proposal = view["proposals"][0]
        store = app.state.workbench.approvals
        store.decide(proposal["proposal_id"], proposal["version"], "approve")
        store.claim_file(proposal["proposal_id"])
    with local_client(make_app(tmp_path, calls, file_mutations=True)) as client:
        login(client)
        view = client.get(f"/api/sessions/{sid}").json()
        assert view["proposals"][0]["status"] == "uncertain"
        response = client.post(
            f"/api/sessions/{sid}/resume",
            headers=HEADERS,
            json={"checkpoint_id": view["history"]["checkpoint_id"], "request_id": "manual-resume"},
        )
        assert response.status_code == 202
        assert wait_run(client, response.json()["run_id"])["status"] == "completed", client.get(
            f"/api/sessions/{sid}"
        ).json()
        assert not (tmp_path / "workspace/uncertain.txt").exists()


def test_command_approve_outputs_and_independent_repeat(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path; p=Path('count.txt'); "
        "p.write_text(p.read_text()+'x' if p.exists() else 'x'); print('done')"
    )
    calls = [
        {
            "name": "propose_command",
            "args": {"executable": sys.executable, "argv": ["-c", script], "timeout_seconds": 5},
            "id": "command-one",
        }
    ]
    with local_client(
        make_app(tmp_path, calls, allowed_executables=frozenset({sys.executable}))
    ) as client:
        login(client)
        sid = session(client)
        for index in range(2):
            proposal = begin(client, sid, f"command-run-{index}")["proposals"][0]
            response = decision(client, sid, proposal, request=f"command-decision-{index}")
            assert response.status_code == 202, response.text
            assert wait_run(client, response.json()["run_id"])["status"] == "completed", client.get(
                f"/api/sessions/{sid}"
            ).json()
            assert (
                decision(client, sid, proposal, request=f"command-decision-{index}").json()[
                    "run_id"
                ]
                == response.json()["run_id"]
            )
        assert (tmp_path / "workspace/count.txt").read_text() == "xx"
        final = client.get(f"/api/sessions/{sid}").json()["proposals"]
        assert len(final) == 2
        assert final[0]["result"]["returncode"] == 0 and final[0]["result"]["stdout"] == "done\n"


@pytest.mark.parametrize("cancel", [False, True])
def test_command_timeout_and_stop_are_durable(tmp_path: Path, cancel: bool) -> None:
    script = (
        "from pathlib import Path; import time; Path('started').write_text('yes'); "
        "time.sleep(20); Path('late').write_text('bad')"
    )
    calls = [
        {
            "name": "propose_command",
            "args": {
                "executable": sys.executable,
                "argv": ["-c", script],
                "timeout_seconds": 5 if cancel else 0.2,
            },
            "id": "slow",
        }
    ]
    with local_client(
        make_app(tmp_path, calls, allowed_executables=frozenset({sys.executable}))
    ) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        response = decision(client, sid, proposal)
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        if cancel:
            deadline = time.monotonic() + 5
            while not (tmp_path / "workspace/started").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert (tmp_path / "workspace/started").exists()
            assert client.post(f"/api/runs/{run_id}/cancel", headers=HEADERS).status_code == 200
        wait_run(client, run_id)
        final = client.get(f"/api/sessions/{sid}").json()["proposals"][0]
        assert final["status"] == ("cancelled" if cancel else "failed")
        if not cancel:
            assert final["result"]["code"] == "timeout"
        assert not (tmp_path / "workspace/late").exists()
        if cancel:
            view = client.get(f"/api/sessions/{sid}").json()
            response = client.post(
                f"/api/sessions/{sid}/resume",
                headers=HEADERS,
                json={
                    "checkpoint_id": view["history"]["checkpoint_id"],
                    "request_id": "cancel-recovery",
                },
            )
            assert response.status_code == 202
            assert wait_run(client, response.json()["run_id"])["status"] == "completed"
            assert (
                client.get(f"/api/sessions/{sid}").json()["proposals"][0]["status"] == "cancelled"
            )


def test_apply_completed_but_result_record_failed_is_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = [{"name": "write", "args": {"path": "written.txt", "content": "written"}, "id": "one"}]
    app = make_app(tmp_path, calls, file_mutations=True)
    with local_client(app) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        store = app.state.workbench.approvals
        original = store.finish_result

        def fail_success(proposal_id: str, status: str, result: dict[str, Any]) -> None:
            if status == "completed":
                raise OSError("Simulated result persistence failure after atomic replace")
            original(proposal_id, status, result)

        monkeypatch.setattr(store, "finish_result", fail_success)
        response = decision(client, sid, proposal)
        assert wait_run(client, response.json()["run_id"])["status"] == "completed"
        assert (tmp_path / "workspace/written.txt").read_text() == "written"
        assert client.get(f"/api/sessions/{sid}").json()["proposals"][0]["status"] == "uncertain"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_command_bounded_output_and_nonzero_exit(tmp_path: Path, exit_code: int) -> None:
    calls = [
        {
            "name": "propose_command",
            "args": {
                "executable": sys.executable,
                "argv": ["-c", f"import sys; print('line\\n'*10000); sys.exit({exit_code})"],
                "timeout_seconds": 5,
            },
            "id": "bounded",
        }
    ]
    with local_client(
        make_app(tmp_path, calls, allowed_executables=frozenset({sys.executable}))
    ) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
        response = decision(client, sid, proposal)
        assert wait_run(client, response.json()["run_id"])["status"] == "completed"
        final = client.get(f"/api/sessions/{sid}").json()["proposals"][0]
        assert final["status"] == ("completed" if exit_code == 0 else "failed")
        assert final["result"]["returncode"] == exit_code
        assert "[truncated]" in final["result"]["stdout"]
        assert len(final["result"]["stdout"].encode()) < 51 * 1024
        assert final["result"]["elapsed_seconds"] >= 0


def test_disabled_capability_after_restart_allows_rejection_only(tmp_path: Path) -> None:
    calls = [{"name": "write", "args": {"path": "disabled.txt", "content": "data"}, "id": "one"}]
    with local_client(make_app(tmp_path, calls, file_mutations=True)) as client:
        login(client)
        sid = session(client)
        proposal = begin(client, sid)["proposals"][0]
    with local_client(make_app(tmp_path, calls, file_mutations=False)) as client:
        login(client)
        assert decision(client, sid, proposal).status_code == 409
        response = decision(client, sid, proposal, "reject", request="reject-disabled")
        assert response.status_code == 202
        assert wait_run(client, response.json()["run_id"])["status"] == "completed"
        assert not (tmp_path / "workspace/disabled.txt").exists()


def test_legacy_command_store_migrates_and_cli_claim_remains_valid(tmp_path: Path) -> None:
    database = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(database)) as db:
        db.execute(
            "CREATE TABLE command_proposals (proposal_id TEXT PRIMARY KEY,session_id TEXT,"
            "workspace TEXT,args_json TEXT,status TEXT,result_json TEXT)"
        )
    paths = WorkspacePathPolicy(tmp_path)
    store = CommandApprovalStore(database)
    args = ProcessArguments(executable="echo", argv=["ok"], timeout_seconds=1)
    proposal = store.propose(
        session_id="legacy", workspace=paths, args=args, allowed_executables=frozenset({"echo"})
    )
    claimed = store.claim(
        proposal.proposal_id,
        workspace=paths,
        allowed_executables=frozenset({"echo"}),
        expected=proposal,
    )
    assert claimed.status == "claimed"
    with pytest.raises(ValueError, match="not repeatable"):
        store.claim(proposal.proposal_id, workspace=paths, allowed_executables=frozenset({"echo"}))
