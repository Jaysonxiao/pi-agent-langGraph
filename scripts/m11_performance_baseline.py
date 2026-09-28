"""Measure local authenticated TCP prompt latency with the deterministic fake tool model."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import tempfile
from math import ceil
from pathlib import Path
from time import perf_counter

from pi_agent.client.client import RemoteClient
from pi_agent.client.transport import connect_tcp
from pi_agent.server.app import ServerOptions, create_server_application

TOKEN = "m11-local-performance-token"


async def measure(samples: int, warmup: int) -> dict[str, object]:
    previous_token = os.environ.get("PI_AGENT_REMOTE_TOKEN")
    os.environ["PI_AGENT_REMOTE_TOKEN"] = TOKEN
    try:
        with tempfile.TemporaryDirectory(prefix="pi-agent-m11-benchmark-") as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "probe.txt").write_text("synthetic performance probe", encoding="utf-8")
            server = create_server_application(
                ServerOptions(
                    workspace=workspace,
                    database=root / "sessions.sqlite",
                    provider="fake",
                    port=0,
                )
            )
            port = await server.start()
            client = RemoteClient(lambda: connect_tcp(port))
            try:
                await client.connect()

                async def one_prompt() -> float:
                    session = await client.create_session()
                    started = perf_counter()
                    await client.prompt(session.session_id, "Read probe.txt and summarize")
                    return (perf_counter() - started) * 1000

                for _ in range(warmup):
                    await one_prompt()
                durations = [await one_prompt() for _ in range(samples)]
                ordered = sorted(durations)
                percentile_index = max(0, ceil(0.95 * samples) - 1)
                return {
                    "benchmark": "authenticated-loopback-fake-tool-turn",
                    "python": platform.python_version(),
                    "os": platform.platform(),
                    "samples": samples,
                    "warmup": warmup,
                    "latency_ms": {
                        "min": round(ordered[0], 3),
                        "median": round(statistics.median(ordered), 3),
                        "p95_nearest_rank": round(ordered[percentile_index], 3),
                        "max": round(ordered[-1], 3),
                        "mean": round(statistics.fmean(ordered), 3),
                    },
                }
            finally:
                await client.close()
                await server.close()
    finally:
        if previous_token is None:
            os.environ.pop("PI_AGENT_REMOTE_TOKEN", None)
        else:
            os.environ["PI_AGENT_REMOTE_TOKEN"] = previous_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.samples <= 1_000:
        parser.error("--samples must be between 1 and 1000")
    if not 0 <= args.warmup <= 100:
        parser.error("--warmup must be between 0 and 100")
    result = asyncio.run(measure(args.samples, args.warmup))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
