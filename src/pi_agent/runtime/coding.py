"""Prepare durable proposals, suspend the graph, and execute only persisted decisions."""

import asyncio
import difflib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import ToolCall, ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from pi_agent.domain.approval import PendingFileChange
from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.runtime.read_only import ReadOnlyWorkspacePathPolicy
from pi_agent.tools.approval_store import ApprovalStore, DurableProposal
from pi_agent.tools.base import ExecutableTool, ToolDefinition
from pi_agent.tools.command_approval import execute_claimed_command
from pi_agent.tools.file_apply import apply_approved_file_change
from pi_agent.tools.file_mutation import (
    EditArguments,
    FileChangePlanner,
    FileMutationError,
    WriteArguments,
    to_pending_file_change,
)
from pi_agent.tools.process import ProcessArguments, ProcessExecutionError

MAX_FILE_BYTES = 32 * 1024


def _unreachable(_args: Any) -> str:
    raise ValueError("This tool must use the durable approval executor.")


def coding_definitions(files: bool, executables: frozenset[str]) -> tuple[ExecutableTool, ...]:
    definitions: list[ExecutableTool] = []
    if files:
        definitions.extend(
            [
                ToolDefinition(
                    "write",
                    "Propose a UTF-8 file creation/replacement for human approval.",
                    WriteArguments,
                    _unreachable,
                ),
                ToolDefinition(
                    "edit",
                    "Propose a unique exact text replacement for human approval.",
                    EditArguments,
                    _unreachable,
                ),
            ]
        )
    if executables:
        definitions.append(
            ToolDefinition(
                "propose_command",
                "Propose exact executable/argv for human approval. Allowed executables: "
                + json.dumps(sorted(executables)),
                ProcessArguments,
                _unreachable,
            )
        )
    return tuple(definitions)


def proposal_projection(proposal: DurableProposal) -> dict[str, Any]:
    """Only browser-reviewable fields; internal absolute file target stays server-owned."""
    payload = proposal.payload
    return {
        "proposal_id": proposal.proposal_id,
        "version": proposal.version,
        "kind": proposal.kind,
        "status": proposal.status,
        "workspace": proposal.workspace,
        "operation": payload.get("operation", "command"),
        "path": payload.get("path"),
        "diff": payload.get("diff"),
        "before_text": payload.get("before_text"),
        "after_text": payload.get("after_text"),
        "args": payload.get("args"),
        "result": proposal.result,
    }


@dataclass(frozen=True, slots=True)
class CodingExecutor:
    store: ApprovalStore
    workspace: Path
    files: bool
    executables: frozenset[str]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in coding_definitions(self.files, self.executables))

    def prepare(self, call: ToolCall, session: str, message: str) -> DurableProposal:
        if call["name"] not in self.names:
            raise ValueError("Capability is not enabled by this server.")
        paths = ReadOnlyWorkspacePathPolicy(self.workspace)
        payload: dict[str, Any]
        if call["name"] == "propose_command":
            args = ProcessArguments.model_validate(call["args"])
            if args.executable not in self.executables:
                raise ValueError("Executable is not in the server allowlist.")
            if len(args.model_dump_json().encode()) > MAX_FILE_BYTES:
                raise ValueError("Command proposal is too large.")
            kind, payload = "command", {"args": args.model_dump()}
        else:
            raw = call["args"]
            target = paths.resolve(str(raw.get("path", "")), must_exist=call["name"] == "edit")
            if target.exists() and target.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("File exceeds the 32 KiB review limit.")
            if len(json.dumps(raw).encode()) > 6 * MAX_FILE_BYTES:
                raise ValueError("File arguments exceed the review limit.")
            planner = FileChangePlanner(paths)
            prepared = (
                planner.prepare_write(WriteArguments.model_validate(raw))
                if call["name"] == "write"
                else planner.prepare_edit(EditArguments.model_validate(raw))
            )
            if len(prepared.after_text.encode()) > MAX_FILE_BYTES:
                raise ValueError("File exceeds the 32 KiB review limit.")
            if prepared.before_text == prepared.after_text:
                raise ValueError("File proposal makes no change.")
            relative = str(prepared.target.relative_to(paths.root))
            diff = "\n".join(
                difflib.unified_diff(
                    (prepared.before_text or "").splitlines(),
                    prepared.after_text.splitlines(),
                    fromfile=f"before/{relative}",
                    tofile=f"after/{relative}",
                    lineterm="",
                )
            )
            kind = "file"
            payload = {
                "operation": prepared.operation,
                "path": relative,
                "requested_path": prepared.requested_path,
                "before_text": prepared.before_text,
                "after_text": prepared.after_text,
                "diff": diff,
                "change": to_pending_file_change(prepared, preview=diff),
            }
        return self.store.prepare(
            session=session,
            workspace=str(paths.root),
            message=message,
            call=str(call["id"]),
            kind=kind,
            payload=payload,
        )

    async def execute(
        self,
        call: ToolCall,
        *,
        session: str,
        message: str,
        token: AsyncCancellationToken,
    ) -> ToolMessage:
        identity = self.store.identity(session, message, str(call["id"]))
        proposal = self.store.proposal(identity)
        try:
            if proposal is None:
                proposal = self.prepare(call, session, message)
            # Keep interrupt positions stable when this multi-call node restarts.
            # Earlier completed calls consume their old answer and replay only the stored result.
            answer = interrupt({"proposal_id": proposal.proposal_id, "version": proposal.version})
            proposal = self.store.proposal(identity)
            assert proposal is not None
            if answer != identity or proposal.status == "pending":
                raise ValueError("A persisted human decision is required.")
            if proposal.status == "approved":
                token.raise_if_cancelled()
                if (
                    proposal.workspace != str(self.workspace.resolve())
                    or call["name"] not in self.names
                ):
                    raise ValueError("Approved workspace or capability is no longer available.")
                paths = ReadOnlyWorkspacePathPolicy(self.workspace)
                if proposal.kind == "file":
                    payload = proposal.payload
                    target = paths.resolve(
                        payload["requested_path"], must_exist=payload["operation"] == "edit"
                    )
                    if str(target) != payload["change"]["path"]:
                        raise ValueError("File target changed after approval.")
                    if target.exists() and target.stat().st_size > MAX_FILE_BYTES:
                        raise ValueError("File exceeds the review limit.")
                    self.store.claim_file(identity)
                    # Bounded synchronous apply cannot leave a worker outliving its owner.
                    # All file operations in one Web process are serialized by the event loop.
                    applied = apply_approved_file_change(
                        {
                            "pending_change": cast(PendingFileChange, payload["change"]),
                            "approval_status": "approved",
                            "rejection_reason": None,
                        },
                        paths,
                    )
                    self.store.finish_result(identity, "completed", asdict(applied))
                else:
                    claimed = self.store.claim(
                        identity,
                        workspace=paths,
                        allowed_executables=self.executables,
                        expected=self.store.get(identity),
                    )
                    await execute_claimed_command(
                        self.store,
                        claimed,
                        workspace=paths,
                        allowed_executables=self.executables,
                        cancellation_token=token,
                    )
            proposal = self.store.proposal(identity)
            assert proposal is not None
            result = proposal.result or {"status": proposal.status}
            success = proposal.status == "completed" and result.get("returncode", 0) == 0
            return self.result(call, result, success, identity)
        except GraphInterrupt:
            raise
        except asyncio.CancelledError:
            current = self.store.proposal(identity)
            if current is not None and current.status == "claimed":
                self.store.finish_result(identity, "cancelled", {"error": "操作已取消。"})
            raise
        except Exception as error:
            code = getattr(error, "code", "execution_failed")
            safe_error = {"error": "操作未完成, 请核对提案或重新生成。", "code": code}
            current = self.store.proposal(identity)
            if current is not None and current.status in {"approved", "claimed"}:
                uncertain = (
                    isinstance(error, ProcessExecutionError) and error.code == "execution_failed"
                ) or (
                    current.status == "claimed"
                    and not isinstance(error, (FileMutationError, ProcessExecutionError))
                )
                self.store.finish_result(
                    identity, "uncertain" if uncertain else "failed", safe_error
                )
            return self.result(call, safe_error, False, identity)

    @staticmethod
    def result(
        call: ToolCall, payload: Mapping[str, Any], success: bool, identity: str
    ) -> ToolMessage:
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False),
            name=call["name"],
            tool_call_id=str(call["id"]),
            id=f"tool-result-{identity}",
            status="success" if success else "error",
        )
