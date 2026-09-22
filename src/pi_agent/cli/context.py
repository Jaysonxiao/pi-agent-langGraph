"""Content-free context inspection using the same pipeline as model_node."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TextIO

from langchain_core.messages import HumanMessage

from pi_agent.context import ContextConfig, inspect_model_context
from pi_agent.security import WorkspacePathPolicy


def add_context_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    context = commands.add_parser("context")
    subcommands = context.add_subparsers(dest="context_command", required=True)
    inspect = subcommands.add_parser("inspect")
    inspect.add_argument("--provider", choices=("fake",), default="fake")
    inspect.add_argument("--workspace", type=Path, default=Path.cwd())
    inspect.add_argument("--active-path", default=".")
    inspect.add_argument("--global-instructions", type=Path)
    inspect.add_argument("--prompt", default="hello")
    inspect.add_argument("--max-bytes", type=int)
    inspect.add_argument("--max-tokens", type=int)


def run_context_cli(args: argparse.Namespace, output: TextIO) -> int:
    try:
        prepared = inspect_model_context(
            (HumanMessage(args.prompt),),
            ContextConfig(
                workspace_policy=WorkspacePathPolicy(args.workspace),
                active_path=args.active_path,
                global_instruction_file=args.global_instructions,
                max_bytes=args.max_bytes,
                max_tokens=args.max_tokens,
            ),
        )
    except (ValueError, OSError, TypeError) as error:
        output.write(
            json.dumps({"error": "context_error", "exception_type": type(error).__name__}) + "\n"
        )
        output.flush()
        return 1
    output.write(json.dumps(prepared.diagnostic(), ensure_ascii=False) + "\n")
    output.flush()
    return 0
