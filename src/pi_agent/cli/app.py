"""Minimal fake-provider CLI entry point for the M5 learning slice."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO, cast

from pi_agent.cli.cancel import CancellationToken, iter_cancellable
from pi_agent.cli.command import add_command_parser, run_command_cli
from pi_agent.cli.context import add_context_parser, run_context_cli
from pi_agent.cli.eval import add_eval_parser, run_eval_cli
from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.read_only import CliWorkspacePathPolicy
from pi_agent.cli.render import render_event
from pi_agent.cli.runtime import stream_provider_session
from pi_agent.cli.signals import sigint_cancels
from pi_agent.closing import close_iterator
from pi_agent.domain import create_initial_state
from pi_agent.events import iter_jsonl, iter_terminal_once, project_stream_chunks
from pi_agent.events.stream import StreamEvent
from pi_agent.events.terminal import run_outcome
from pi_agent.events.trace import sanitized_trace
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models import FakeChatModel
from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.config import ModelOptions, resolve_model_config
from pi_agent.models.http_client import build_async_provider_client
from pi_agent.runtime.policy import RetryPolicy
from pi_agent.sessions import SqliteSessionCatalog

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CANCELLED = 130


def build_parser() -> argparse.ArgumentParser:
    """Build the M5 run CLI plus the M6 session-management entry point."""

    parser = argparse.ArgumentParser(prog="pi-agent")
    parser.add_argument("--provider", choices=("fake", "compatible"), default="fake")
    parser.add_argument("--prompt")
    parser.add_argument("--events", choices=("text", "jsonl"), default="text")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--allow-executable", action="append", default=[])
    parser.add_argument("--trace-file", type=Path)
    commands = parser.add_subparsers(dest="command")
    add_context_parser(commands)
    add_command_parser(commands)
    add_eval_parser(commands)
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


async def _run_compatible_cli(args: argparse.Namespace, output: TextIO) -> int:
    """Run one explicitly configured persistent provider turn."""
    if args.database is None or args.session_id is None or args.workspace is None:
        raise ValueError("compatible requires --database, --session-id and --workspace.")
    configuration = resolve_model_config(
        ModelOptions(provider="compatible", model=args.model, base_url=args.base_url),
        os.environ,
    )
    client = build_async_provider_client(configuration)
    model = CompatibleAsyncChatModel(client)
    options = ProviderCliOptions(
        provider="compatible",
        prompt=args.prompt,
        events=args.events,
        database=args.database,
        session_id=args.session_id,
        workspace=args.workspace,
    )
    trace_target: Path | None = None
    if args.trace_file is not None:
        trace_target = CliWorkspacePathPolicy(args.workspace).resolve(
            str(args.trace_file), must_exist=False
        )
        if not trace_target.parent.is_dir() or (
            trace_target.exists() and not trace_target.is_file()
        ):
            raise ValueError("Trace destination must be a workspace file in an existing directory.")
    outcome: str | None = None
    try:
        async with asyncio.timeout(configuration.run_timeout_seconds):
            async for event in stream_provider_session(
                options,
                model=model,
                message_id=f"input-{os.urandom(8).hex()}",
                retry_policy=RetryPolicy(
                    max_attempts=configuration.max_attempts,
                    run_timeout_seconds=configuration.run_timeout_seconds,
                ),
                request_timeout_seconds=configuration.timeout_seconds,
                allowed_executables=frozenset(args.allow_executable),
            ):
                current = run_outcome(event)
                if current is not None:
                    outcome = current
                output.write(_format_event(event, args.events))
                output.flush()
                if trace_target is not None:
                    with trace_target.open("a", encoding="utf-8") as trace_stream:
                        trace_stream.write(json.dumps(sanitized_trace(event)) + "\n")
        if outcome is None:
            event = StreamEvent(
                sequence=0, kind="error", node="runtime", payload={"code": "missing_terminal"}
            )
            output.write(_format_event(event, args.events))
            output.flush()
            return EXIT_FAILURE
        return EXIT_SUCCESS if outcome == "success" else EXIT_FAILURE
    finally:
        await model.aclose()


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
    if args.command == "command":
        try:
            return asyncio.run(run_command_cli(args, sys.stdout))
        except KeyboardInterrupt:
            return EXIT_CANCELLED
        except Exception as exc:
            sys.stderr.write(f"Command review failed: {type(exc).__name__}.\n")
            return EXIT_FAILURE
    if args.command == "eval":
        try:
            return run_eval_cli(args, sys.stdout)
        except KeyboardInterrupt:
            return EXIT_CANCELLED
        except Exception as exc:
            # 评测 CLI 只报告异常类型, 避免把 prompt、回复正文或凭据写到 stderr.
            sys.stderr.write(f"Eval run failed: {type(exc).__name__}.\n")
            return EXIT_FAILURE
    if args.prompt is None:
        parser.error("--prompt is required unless running a session command.")
    if args.provider == "compatible":
        try:
            return asyncio.run(_run_compatible_cli(args, sys.stdout))
        except KeyboardInterrupt:
            return EXIT_CANCELLED
        except Exception as exc:
            # Runtime diagnostics must not echo provider bodies or credentials.
            sys.stderr.write(f"Provider run failed: {type(exc).__name__}.\n")
            return EXIT_FAILURE
    return run_cli(args, sys.stdout)
