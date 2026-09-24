"""Explicit terminal approval for durable model-proposed commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.command_approval import (
    CommandApprovalStore,
    CommandProposal,
    execute_claimed_command,
)


def add_command_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    command = commands.add_parser("command", help="Review a model-proposed command")
    actions = command.add_subparsers(dest="command_action", required=True)
    for name in ("show", "approve", "reject"):
        action = actions.add_parser(name)
        action.add_argument("proposal_id")
        action.add_argument("--database", type=Path, required=True)
        if name == "approve":
            action.add_argument("--workspace", type=Path, required=True)
            action.add_argument("--allow-executable", action="append", required=True)


def _describe(proposal: CommandProposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.proposal_id,
        "session_id": proposal.session_id,
        "workspace": proposal.workspace,
        "executable": proposal.args.executable,
        "argv": proposal.args.argv,
        "timeout_seconds": proposal.args.timeout_seconds,
        "status": proposal.status,
    }


async def run_command_cli(args: argparse.Namespace, output: TextIO) -> int:
    """Show exact argv, require a typed human confirmation, then claim once."""
    store = CommandApprovalStore(args.database)
    displayed = store.get(args.proposal_id)
    description = _describe(displayed)
    output.write(json.dumps(description, ensure_ascii=False) + "\n")
    output.flush()
    if args.command_action == "show":
        return 0
    if args.command_action == "reject":
        store.reject(args.proposal_id)
        return 0
    if args.command_action != "approve":
        raise ValueError("Unknown command action.")
    if description["status"] != "pending":
        raise ValueError("Command proposal is not pending.")
    if not sys.stdin.isatty():
        raise ValueError("Interactive terminal approval is required.")
    response = input(f"Type 'approve {args.proposal_id}' to execute exactly this command: ")
    if response != f"approve {args.proposal_id}":
        raise ValueError("Command approval was not confirmed.")
    workspace = WorkspacePathPolicy(args.workspace)
    allowed_executables = frozenset(args.allow_executable)
    proposal = store.claim(
        args.proposal_id,
        workspace=workspace,
        allowed_executables=allowed_executables,
        expected=displayed,
    )
    result = await execute_claimed_command(
        store,
        proposal,
        workspace=workspace,
        allowed_executables=allowed_executables,
    )
    output.write(result.model_dump_json() + "\n")
    output.flush()
    return 0 if result.returncode == 0 else 1
