"""Minimal fake-provider CLI entry point for the M5 learning slice."""

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO, cast

from pi_agent.cli.cancel import CancellationToken, iter_cancellable
from pi_agent.cli.context import add_context_parser, run_context_cli
from pi_agent.cli.render import render_event
from pi_agent.cli.signals import sigint_cancels
from pi_agent.closing import close_iterator
from pi_agent.domain import create_initial_state
from pi_agent.events import iter_jsonl, iter_terminal_once, project_stream_chunks
from pi_agent.events.stream import StreamEvent
from pi_agent.events.terminal import run_outcome
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models import FakeChatModel
from pi_agent.sessions import SqliteSessionCatalog

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CANCELLED = 130


def build_parser() -> argparse.ArgumentParser:
    """Build the M5 run CLI plus the M6 session-management entry point."""

    parser = argparse.ArgumentParser(prog="pi-agent")
    parser.add_argument("--provider", choices=("fake",), default="fake")
    parser.add_argument("--prompt")
    parser.add_argument("--events", choices=("text", "jsonl"), default="text")
    commands = parser.add_subparsers(dest="command")
    add_context_parser(commands)
    session_parser = commands.add_parser("session")
    session_commands = session_parser.add_subparsers(dest="session_command", required=True)
    list_parser = session_commands.add_parser("list")
    list_parser.add_argument("--database", type=Path, required=True)
    return parser


def _format_event(event: StreamEvent, mode: str) -> str:
    if mode == "jsonl":
        return next(iter_jsonl((event,)))
    return f"{render_event(event)}\n"


def run_cli(args: argparse.Namespace, output: TextIO) -> int:
    """Run one fake-provider request and write its projected events."""

    token = CancellationToken()
    # CLI 拥有 graph.stream, 任何退出路径都要显式 close, 不靠 GC.
    raw_chunks = cast(
        Iterable[tuple[str, object]],
        build_minimal_graph().stream(
            create_initial_state(args.prompt),
            context=RunContext(model=FakeChatModel()),
            stream_mode=["updates", "messages", "custom"],
        ),
    )
    events = iter_terminal_once(iter_cancellable(project_stream_chunks(raw_chunks), token))
    outcome: str | None = None
    try:
        with sigint_cancels(token):
            for event in events:
                current = run_outcome(event)
                if current is not None:
                    outcome = current
                output.write(_format_event(event, args.events))
                # Each event is an observable streaming boundary, including through pipes.
                output.flush()
    finally:
        close_iterator(events)
        close_iterator(raw_chunks)

    if token.cancelled:
        return EXIT_CANCELLED
    if outcome != "success":
        return EXIT_FAILURE
    return EXIT_SUCCESS


def run_session_cli(args: argparse.Namespace, output: TextIO) -> int:
    """Run one session-management command without constructing an agent graph."""
    if args.session_command != "list":
        raise ValueError(f"Unsupported session command: {args.session_command}")

    for record in SqliteSessionCatalog(args.database).list_sessions():
        output.write(
            json.dumps(
                {
                    "session_id": record.session_id,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        output.flush()
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run the CLI against stdout."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "session":
        return run_session_cli(args, sys.stdout)
    if args.command == "context":
        return run_context_cli(args, sys.stdout)
    if args.prompt is None:
        parser.error("--prompt is required unless running a session command.")
    return run_cli(args, sys.stdout)
