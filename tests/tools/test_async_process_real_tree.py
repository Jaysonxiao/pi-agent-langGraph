"""Host process-group evidence, including children retaining pipes after parent exit."""

import asyncio
import csv
import subprocess
import sys
from pathlib import Path

import pytest

from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_process import run_controlled_async_process_result
from pi_agent.tools.output import TextOutputBudget
from pi_agent.tools.process import ProcessArguments, ProcessExecutionError


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        output = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return any(len(row) > 1 and row[1] == str(pid) for row in csv.reader(output.splitlines()))
    state = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(state) and not state.startswith("Z")


@pytest.mark.parametrize("parent_exits", [False, True])
def test_timeout_handles_real_descendants(tmp_path: Path, parent_exits: bool) -> None:
    async def scenario() -> None:
        child_script = "import time; time.sleep(20)"
        parent_script = (
            "import subprocess,sys,time; from pathlib import Path; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_script!r}]); "
            "Path('child.pid').write_text(str(p.pid)); "
            + ("sys.exit(0)" if parent_exits else "time.sleep(20)")
        )
        try:
            async with asyncio.timeout(5):
                with pytest.raises(ProcessExecutionError) as failure:
                    await run_controlled_async_process_result(
                        ProcessArguments(
                            executable=sys.executable,
                            argv=["-c", parent_script],
                            timeout_seconds=0.5,
                        ),
                        allowed_executables=frozenset({sys.executable}),
                        cwd=str(tmp_path),
                        token=AsyncCancellationToken(),
                        output_budget=TextOutputBudget(),
                    )
            if parent_exits and sys.platform == "win32":
                assert failure.value.code == "execution_failed"
            else:
                assert failure.value.code == "timeout"
                pid = int((tmp_path / "child.pid").read_text())
                for _ in range(50):
                    if not alive(pid):
                        break
                    await asyncio.sleep(0.02)
                assert not alive(pid)
        finally:
            # Windows cannot infer an orphan's tree from an already-exited parent.
            # The test owns the synthetic descendant and reaps it explicitly in this case.
            if parent_exits and sys.platform == "win32" and (tmp_path / "child.pid").exists():
                subprocess.run(
                    ["taskkill", "/PID", (tmp_path / "child.pid").read_text(), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )

    asyncio.run(scenario())
