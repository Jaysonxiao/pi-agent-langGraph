"""Common durable proposal state in the existing CLI command table."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pi_agent.tools.command_approval import CommandApprovalStore
from pi_agent.tools.process import ProcessArguments


@dataclass(frozen=True, slots=True)
class DurableProposal:
    proposal_id: str
    session_id: str
    workspace: str
    kind: str
    message_id: str
    tool_call_id: str
    version: str
    status: str
    decision: str | None
    payload: dict[str, Any]
    result: dict[str, Any] | None


class ApprovalStore(CommandApprovalStore):
    def initialize(self) -> None:
        with self._connect():
            pass

    @staticmethod
    def identity(session: str, message: str, call: str) -> str:
        return hashlib.sha256(json.dumps([session, message, call]).encode()).hexdigest()[:24]

    def proposal(self, proposal_id: str) -> DurableProposal | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT proposal_id,session_id,workspace,kind,message_id,tool_call_id,version,"
                "status,decision,payload_json,result_json FROM command_proposals "
                "WHERE proposal_id=? AND payload_json IS NOT NULL",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return DurableProposal(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            json.loads(row[9]),
            json.loads(row[10]) if row[10] else None,
        )

    def proposals(
        self, session_id: str, *, message_ids: tuple[str, ...] | None = None
    ) -> list[DurableProposal]:
        if message_ids == ():
            return []
        query = (
            "SELECT proposal_id FROM command_proposals WHERE session_id=? "
            "AND payload_json IS NOT NULL"
        )
        parameters: tuple[str, ...] = (session_id,)
        if message_ids is None:
            query += " ORDER BY rowid DESC LIMIT 50"
        else:
            query += f" AND message_id IN ({','.join('?' for _ in message_ids)}) ORDER BY rowid"
            parameters += message_ids
        with self._connect() as db:
            ids = [row[0] for row in db.execute(query, parameters)]
        return [proposal for pid in ids if (proposal := self.proposal(pid)) is not None]

    def prepare(
        self,
        *,
        session: str,
        workspace: str,
        message: str,
        call: str,
        kind: str,
        payload: dict[str, Any],
    ) -> DurableProposal:
        proposal_id = self.identity(session, message, call)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        version = hashlib.sha256(json.dumps([workspace, kind, encoded]).encode()).hexdigest()
        args_json = (
            ProcessArguments.model_validate(payload["args"]).model_dump_json(exclude_none=True)
            if kind == "command"
            else "{}"
        )
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO command_proposals "
                "(proposal_id,session_id,workspace,args_json,status,kind,payload_json,"
                "message_id,tool_call_id,version) VALUES (?,?,?,?,'pending',?,?,?,?,?)",
                (proposal_id, session, workspace, args_json, kind, encoded, message, call, version),
            )
        proposal = self.proposal(proposal_id)
        if proposal is None or proposal.version != version:
            raise ValueError("Proposal operation identity conflicts with its content.")
        return proposal

    def decide(self, proposal_id: str, version: str, decision: str) -> DurableProposal:
        if decision not in {"approve", "reject"}:
            raise ValueError("Invalid approval decision.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,version,decision FROM command_proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if row is None or row[1] != version:
                raise ValueError("Proposal version changed; refresh before deciding.")
            if row[2] == decision:
                pass
            elif row[0] != "pending" or row[2] is not None:
                raise ValueError("Proposal already has a different decision.")
            else:
                db.execute(
                    "UPDATE command_proposals SET status=?,decision=? WHERE proposal_id=?",
                    ("approved" if decision == "approve" else "rejected", decision, proposal_id),
                )
        proposal = self.proposal(proposal_id)
        assert proposal is not None
        return proposal

    def claim_file(self, proposal_id: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE command_proposals SET status='claimed' "
                "WHERE proposal_id=? AND kind='file' AND status='approved'",
                (proposal_id,),
            ).rowcount
        if changed != 1:
            raise ValueError("File proposal cannot be executed again.")

    def finish_result(self, proposal_id: str, status: str, result: dict[str, Any]) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE command_proposals SET status=?,result_json=? "
                "WHERE proposal_id=? AND status IN ('claimed','approved')",
                (status, json.dumps(result, ensure_ascii=False), proposal_id),
            ).rowcount
        if changed != 1:
            raise ValueError("Proposal result cannot overwrite a terminal state.")

    def recover_claims(self) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE command_proposals SET status='uncertain',result_json=? "
                "WHERE status='claimed' AND payload_json IS NOT NULL",
                (json.dumps({"error": "服务曾中断, 执行结果需要人工核对;不会自动重跑。"}),),
            )
