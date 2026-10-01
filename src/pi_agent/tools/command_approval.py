"""Durable, fail-closed human approval for model-proposed commands.

A proposal never spawns. Claiming it is a one-way SQLite transition: a crash
after the claim leaves an uncertain operation for manual reconciliation, never
an automatically repeated external side effect.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.base import ToolDefinition
from pi_agent.tools.output import TextOutputBudget
from pi_agent.tools.process import ProcessArguments, ProcessResult


@dataclass(frozen=True, slots=True)
class CommandProposal:
    proposal_id: str
    session_id: str
    workspace: str
    args: ProcessArguments
    status: str


class CommandApprovalStore:
    """Keep approvals in the same durable database as session checkpoints."""

    def __init__(self, database: Path) -> None:
        self.database = database

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=10)
        try:
            with connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS command_proposals (
                        proposal_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        workspace TEXT NOT NULL,
                        args_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        result_json TEXT
                    )"""
                )
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(command_proposals)")
                }
                for name, declaration in {
                    "kind": "TEXT NOT NULL DEFAULT 'command'",
                    "payload_json": "TEXT",
                    "message_id": "TEXT",
                    "tool_call_id": "TEXT",
                    "version": "TEXT",
                    "decision": "TEXT",
                }.items():
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE command_proposals ADD COLUMN {name} {declaration}"
                        )
                yield connection
        finally:
            connection.close()

    def propose(
        self,
        *,
        session_id: str,
        workspace: WorkspacePathPolicy,
        args: ProcessArguments,
        allowed_executables: frozenset[str],
    ) -> CommandProposal:
        if args.executable not in allowed_executables:
            raise ValueError("Executable is not in the configured allowlist.")
        args_json = args.model_dump_json(exclude_none=True)
        identity = json.dumps(
            [session_id, str(workspace.root), json.loads(args_json)],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        proposal_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO command_proposals
                (proposal_id, session_id, workspace, args_json, status)
                VALUES (?, ?, ?, ?, 'pending')""",
                (proposal_id, session_id, str(workspace.root), args_json),
            )
        return self.get(proposal_id)

    def get(self, proposal_id: str) -> CommandProposal:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT session_id, workspace, args_json, status
                FROM command_proposals WHERE proposal_id = ? AND kind='command'""",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Command proposal does not exist.")
        return CommandProposal(
            proposal_id=proposal_id,
            session_id=row[0],
            workspace=row[1],
            args=ProcessArguments.model_validate_json(row[2]),
            status=row[3],
        )

    def reject(self, proposal_id: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE command_proposals SET status = 'rejected' "
                "WHERE proposal_id = ? AND status = 'pending'",
                (proposal_id,),
            ).rowcount
        if changed != 1:
            raise ValueError("Only a pending command proposal can be rejected.")

    def claim(
        self,
        proposal_id: str,
        *,
        workspace: WorkspacePathPolicy,
        allowed_executables: frozenset[str],
        expected: CommandProposal | None = None,
    ) -> CommandProposal:
        """Atomically consume one exact proposal before any external process starts."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT session_id, workspace, args_json, status
                FROM command_proposals WHERE proposal_id = ? AND kind='command'""",
                (proposal_id,),
            ).fetchone()
            if row is None or row[3] not in {"pending", "approved"}:
                raise ValueError("Command proposal is not pending; execution is not repeatable.")
            if expected is not None and (
                expected.proposal_id != proposal_id
                or expected.session_id != row[0]
                or expected.workspace != row[1]
                or expected.args.model_dump_json(exclude_none=True) != row[2]
            ):
                raise ValueError("Command proposal changed after it was displayed.")
            if row[1] != str(workspace.root):
                raise ValueError("Approved workspace differs from the proposed workspace.")
            args = ProcessArguments.model_validate_json(row[2])
            if args.executable not in allowed_executables:
                raise ValueError("Executable is not in the current allowlist.")
            connection.execute(
                "UPDATE command_proposals SET status = 'claimed' WHERE proposal_id = ?",
                (proposal_id,),
            )
        return CommandProposal(proposal_id, row[0], row[1], args, "claimed")

    def finish(
        self, proposal_id: str, result: ProcessResult, *, elapsed_seconds: float | None = None
    ) -> None:
        with self._connect() as connection:
            payload = result.model_dump()
            payload["elapsed_seconds"] = elapsed_seconds
            changed = connection.execute(
                """UPDATE command_proposals SET status = ?, result_json = ?
                WHERE proposal_id = ? AND status = 'claimed'""",
                (
                    "completed" if result.returncode == 0 else "failed",
                    json.dumps(payload, ensure_ascii=False),
                    proposal_id,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("Claimed command result cannot be recorded again.")


def create_command_proposal_tool(
    database: Path,
    *,
    session_id: str,
    workspace: WorkspacePathPolicy,
    allowed_executables: frozenset[str],
) -> ToolDefinition[ProcessArguments]:
    """Expose proposal creation, never direct process execution, to the model."""
    store = CommandApprovalStore(database)

    def propose(args: ProcessArguments) -> str:
        proposal = store.propose(
            session_id=session_id,
            workspace=workspace,
            args=args,
            allowed_executables=allowed_executables,
        )
        return json.dumps(
            {"proposal_id": proposal.proposal_id, "status": proposal.status},
            separators=(",", ":"),
        )

    return ToolDefinition(
        name="propose_command",
        description="Propose an allowlisted command for human approval; never execute it.",
        args_schema=ProcessArguments,
        handler=propose,
    )


async def execute_claimed_command(
    store: CommandApprovalStore,
    proposal: CommandProposal,
    *,
    workspace: WorkspacePathPolicy,
    allowed_executables: frozenset[str],
    output_budget: TextOutputBudget | None = None,
    cancellation_token: AsyncCancellationToken | None = None,
) -> ProcessResult:
    """Execute exactly the claimed argv in the proposed authorized workspace."""
    from pi_agent.tools.async_process import run_controlled_async_process_result

    started = monotonic()
    result = await run_controlled_async_process_result(
        proposal.args,
        allowed_executables=allowed_executables,
        cwd=proposal.workspace,
        workspace=workspace,
        token=cancellation_token or AsyncCancellationToken(),
        output_budget=output_budget or TextOutputBudget(),
    )
    store.finish(proposal.proposal_id, result, elapsed_seconds=monotonic() - started)
    return result
