"""CLI tool-eval scaffold using real workspace tools and durable graph state."""

from collections.abc import Sequence
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import stream_provider_session
from pi_agent.evals.harness import EvalCase, EvalObservation, EvalSuite
from pi_agent.evals.tool_trace import collect_tool_names
from pi_agent.events.terminal import run_outcome
from pi_agent.extensions import HookEvent, HookRegistry

PROBE_TEXT = "synthetic M11 probe is ready"
TOOLS_SUITE = EvalSuite(
    name="tools",
    cases=(
        EvalCase(
            case_id="workspace-list-read",
            prompt="List the workspace, then read probe.txt and summarize it.",
            expected_response=PROBE_TEXT,
            expected_tool_names=("list", "read"),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ToolCaseTrace:
    """Private judge inputs; neither response nor hook identities enter the report."""

    response: str
    events: tuple[HookEvent, ...]
    completed: bool


class _WorkspaceProbeModel:
    """Request actual tools, then form an answer from their returned content."""

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        del config
        results = [message for message in messages if isinstance(message, ToolMessage)]
        if not results:
            return AIMessage(
                content="",
                tool_calls=[
                    {"name": "list", "args": {"path": "."}, "id": "list-1"},
                    {"name": "read", "args": {"path": "probe.txt"}, "id": "read-1"},
                ],
            )
        if [result.name for result in results] != ["list", "read"] or any(
            result.status != "success" for result in results
        ):
            raise RuntimeError("Synthetic tool scenario failed.")
        return AIMessage(content=f"Verified probe: {results[-1].content}")


async def run_tool_case(case: EvalCase) -> ToolCaseTrace:
    """Create isolated fixtures, consume the public CLI runtime, and close resources."""
    with TemporaryDirectory(prefix="pi-agent-m11-eval-") as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        (workspace / "probe.txt").write_text(PROBE_TEXT, encoding="utf-8")
        options = ProviderCliOptions(
            provider="fake",
            prompt=case.prompt,
            events="jsonl",
            database=root / "sessions.sqlite",
            session_id="m11-eval",
            workspace=workspace,
        )
        hooks = HookRegistry()
        observed: list[HookEvent] = []

        async def capture(event: HookEvent) -> None:
            observed.append(event)

        hooks.register("eval-observation", capture)
        response = ""
        completed = False
        async with aclosing(
            stream_provider_session(
                options, model=_WorkspaceProbeModel(), message_id="input-1", hooks=hooks
            )
        ) as events:
            async for event in events:
                if event.kind == "message" and event.payload.get("role") == "assistant":
                    content = event.payload.get("content")
                    if isinstance(content, str):
                        response += content
                outcome = run_outcome(event)
                if outcome is not None:
                    completed = outcome == "success"
        return ToolCaseTrace(response=response, events=tuple(observed), completed=completed)


class FakeToolEvalExecutor:
    """Join the real tool scenario to the learner-owned metadata projection."""

    async def run(self, case: EvalCase) -> EvalObservation:
        trace = await run_tool_case(case)
        if not trace.completed:
            raise RuntimeError("Tool evaluation did not complete.")
        return EvalObservation(
            response=trace.response,
            tool_names=collect_tool_names(trace.events),
        )
