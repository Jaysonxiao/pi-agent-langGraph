"""Public one-shot remote client CLI for M10.8."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from pi_agent.client.client import RemoteClient
from pi_agent.client.transport import connect_tcp
from pi_agent.protocol.messages import SessionSnapshot
from pi_agent.protocol.transport import LOOPBACK_HOST

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CANCELLED = 130
RemoteClientFactory = Callable[[str, int], RemoteClient]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pi-agent-client")
    parser.add_argument("--host", choices=(LOOPBACK_HOST,), default=LOOPBACK_HOST)
    parser.add_argument("--port", type=int, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="create a new durable session")
    snapshot = commands.add_parser("snapshot", help="fetch one authoritative session snapshot")
    snapshot.add_argument("--session-id", required=True)
    prompt = commands.add_parser("prompt", help="send a prompt to an existing session")
    prompt.add_argument("--session-id", required=True)
    prompt.add_argument("--text", required=True)
    cancel = commands.add_parser("cancel", help="cancel the active run in a session")
    cancel.add_argument("--session-id", required=True)
    cancel.add_argument("--run-id", required=True)
    return parser


def create_remote_client(host: str, port: int) -> RemoteClient:
    """Build the transport adapter; credentials are read only by connect_tcp."""
    return RemoteClient(lambda: connect_tcp(port, host=host))


async def dispatch_command(client: RemoteClient, args: argparse.Namespace) -> SessionSnapshot:
    """将解析后的公开命令分派给对应 RemoteClient 操作并返回快照。"""
    # 连接建立、JSON 输出和 finally 关闭由 run_cli() 统一负责。
    if args.command == "create":
        return await client.create_session()
    if args.command == "snapshot":
        return await client.get_snapshot(args.session_id)
    if args.command == "prompt":
        return await client.prompt(args.session_id, args.text)
    if args.command == "cancel":
        return await client.cancel(args.session_id, args.run_id)
    raise ValueError("Unsupported client command.")


async def run_cli(
    args: argparse.Namespace,
    output: TextIO,
    *,
    client_factory: RemoteClientFactory = create_remote_client,
) -> int:
    """Connect once, execute one operation, emit one JSON snapshot, and close."""
    client = client_factory(args.host, args.port)
    try:
        await client.connect()
        snapshot = await dispatch_command(client, args)
        output.write(json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False) + "\n")
        output.flush()
        return EXIT_SUCCESS
    finally:
        await client.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(run_cli(args, sys.stdout))
    except KeyboardInterrupt:
        return EXIT_CANCELLED
    except Exception as error:
        # Error text can include untrusted input or remote details; expose only its type.
        sys.stderr.write(f"Remote command failed: {type(error).__name__}.\n")
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
