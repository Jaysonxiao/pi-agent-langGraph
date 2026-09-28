"""Public compatible CLI telemetry opt-in and privacy boundary."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.cli import app as cli_app
from pi_agent.cli import main


class _ReadToolClient:
    def __init__(self) -> None:
        self.closed = False
        self.bound_tools: tuple[Mapping[str, object], ...] = ()

    def bind_tools(self, tools: Sequence[Mapping[str, object]]) -> None:
        self.bound_tools = tuple(tools)

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        del config
        tool_results = [message for message in messages if isinstance(message, ToolMessage)]
        if tool_results:
            assert tool_results[-1].status == "success"
            return AIMessage(content=f"Summary: {tool_results[-1].content}")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "read",
                    "args": {"path": "probe.txt"},
                    "id": "read-cli-1",
                    "type": "tool_call",
                }
            ],
        )

    async def aclose(self) -> None:
        self.closed = True


def _configure(monkeypatch: pytest.MonkeyPatch, client: _ReadToolClient) -> None:
    monkeypatch.setenv("PI_AGENT_API_KEY", "synthetic-api-key")
    monkeypatch.setenv("PI_AGENT_MODEL", "synthetic-model")
    monkeypatch.setenv("PI_AGENT_BASE_URL", "https://provider.example/v1")
    monkeypatch.setattr(cli_app, "build_async_provider_client", lambda _config: client)


def _args(workspace: Path, database: Path, *options: str) -> list[str]:
    return [
        "--provider",
        "compatible",
        "--workspace",
        str(workspace),
        "--database",
        str(database),
        "--session-id",
        "cli-telemetry",
        "--events",
        "jsonl",
        "--prompt",
        "Read probe.txt and summarize",
        *options,
    ]


def test_compatible_cli_opt_in_records_redacted_run_and_tool_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "probe.txt").write_text("synthetic probe content", encoding="utf-8")
    telemetry_file = workspace / "telemetry.jsonl"
    client = _ReadToolClient()
    _configure(monkeypatch, client)

    exit_code = main(
        _args(
            workspace,
            tmp_path / "sessions.sqlite",
            "--telemetry-file",
            "telemetry.jsonl",
        )
    )
    output = capsys.readouterr()

    assert exit_code == cli_app.EXIT_SUCCESS
    assert "synthetic probe content" in output.out
    assert client.closed
    assert len(client.bound_tools) == 3
    records = [json.loads(line) for line in telemetry_file.read_text(encoding="utf-8").splitlines()]
    spans = [record for record in records if record["kind"] == "span_started"]
    finished = [record for record in records if record["kind"] == "span_finished"]
    metrics = [record for record in records if record["kind"] == "metric"]
    logs = [record for record in records if record["kind"] == "log"]
    assert {span["name"] for span in spans} == {"agent.run", "agent.model", "agent.tool"}
    assert len(spans) == len(finished) == 4
    assert all(record["outcome"] == "completed" for record in finished)
    assert all(record["trace_id"] == spans[0]["trace_id"] for record in spans)
    assert any(
        record["attributes"] == {"outcome": "completed", "phase": "after_tool"}
        for record in metrics
    )
    assert any(record["attributes"].get("tool_name") == "read" for record in logs)
    persisted = telemetry_file.read_text(encoding="utf-8")
    for secret in (
        "synthetic-api-key",
        "synthetic probe content",
        "Read probe.txt and summarize",
        "Summary:",
    ):
        assert secret not in persisted
    assert "synthetic-api-key" not in output.out + output.err


def test_compatible_cli_telemetry_is_opt_in_and_path_rejection_precedes_client_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "probe.txt").write_text("content", encoding="utf-8")
    client = _ReadToolClient()
    _configure(monkeypatch, client)
    assert main(_args(workspace, tmp_path / "sessions.sqlite")) == cli_app.EXIT_SUCCESS
    assert not (workspace / "telemetry.jsonl").exists()
    assert client.closed

    uncreated_client = _ReadToolClient()
    _configure(monkeypatch, uncreated_client)
    exit_code = main(
        _args(workspace, tmp_path / "other.sqlite", "--telemetry-file", "../outside.jsonl")
    )
    assert exit_code == cli_app.EXIT_FAILURE
    assert not uncreated_client.closed
    assert "outside.jsonl" not in capsys.readouterr().err
