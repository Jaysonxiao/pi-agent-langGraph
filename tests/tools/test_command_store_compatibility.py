"""Web approval migrations preserve command records created by the CLI baseline."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.approval_store import ApprovalStore
from pi_agent.tools.command_approval import CommandApprovalStore
from pi_agent.tools.process import ProcessArguments


@pytest.mark.parametrize("status", ["pending", "claimed", "completed", "rejected"])
def test_existing_cli_proposal_survives_web_migration_and_recovery(
    tmp_path: Path, status: str
) -> None:
    database = tmp_path / "legacy.sqlite"
    paths = WorkspacePathPolicy(tmp_path)
    args = ProcessArguments(executable="echo", argv=["legacy"], timeout_seconds=1)
    args_json = args.model_dump_json(exclude_none=True)
    old_result = (
        json.dumps({"returncode": 0, "timed_out": False}) if status == "completed" else None
    )
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "CREATE TABLE command_proposals (proposal_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,"
            "workspace TEXT NOT NULL,args_json TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT)"
        )
        db.execute(
            "INSERT INTO command_proposals VALUES (?,?,?,?,?,?)",
            ("legacy-id", "cli-session", str(paths.root), args_json, status, old_result),
        )

    web = ApprovalStore(database)
    web.initialize()
    web.recover_claims()
    assert web.proposals("cli-session") == []
    cli = CommandApprovalStore(database)
    proposal = cli.get("legacy-id")
    assert proposal.status == status
    assert proposal.session_id == "cli-session"
    assert proposal.workspace == str(paths.root)
    assert proposal.args == args
    with closing(sqlite3.connect(database)) as db:
        assert db.execute(
            "SELECT args_json,result_json FROM command_proposals WHERE proposal_id='legacy-id'"
        ).fetchone() == (args_json, old_result)

    if status == "pending":
        assert (
            cli.claim(
                "legacy-id",
                workspace=paths,
                allowed_executables=frozenset({"echo"}),
                expected=proposal,
            ).status
            == "claimed"
        )
    with pytest.raises(ValueError, match="not repeatable"):
        cli.claim("legacy-id", workspace=paths, allowed_executables=frozenset({"echo"}))
