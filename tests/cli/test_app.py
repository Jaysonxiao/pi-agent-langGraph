"""Acceptance tests for the minimal fake-provider CLI entry point."""

import json
from io import StringIO
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk

from pi_agent.cli import CancellationToken, main
from pi_agent.cli import app as cli_app
from pi_agent.models import FakeChatModel


class _FlushTrackingOutput(StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1
        super().flush()


class _ScriptedGraph:
    def __init__(self, chunks: list[tuple[str, object]]) -> None:
        self._chunks = chunks
        self.stream_mode: object = None
        self.closed = False

    def stream(self, *_args: object, **kwargs: object) -> Any:
        self.stream_mode = kwargs.get("stream_mode")

        def generate() -> Any:
            try:
                yield from self._chunks
            finally:
                self.closed = True

        return generate()


def test_cli_help_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    assert "--provider" in capsys.readouterr().out


def test_cli_fake_provider_renders_text_events(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--provider", "fake", "--prompt", "hello", "--events", "text"])

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines() == [
        "[message] model/assistant: fake reply",
        '[state_update] model: {"status":"completed","error":null}',
    ]


def test_cli_fake_provider_writes_jsonl_events(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--provider", "fake", "--prompt", "hello", "--events", "jsonl"])
    lines = capsys.readouterr().out.splitlines()

    assert exit_code == 0
    assert [json.loads(line)["kind"] for line in lines] == ["message", "state_update"]
    assert [json.loads(line)["sequence"] for line in lines] == [0, 1]


def test_cli_runs_the_stream_inside_sigint_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered: list[bool] = []
    exited: list[bool] = []

    class FakeSigintScope:
        def __enter__(self) -> None:
            entered.append(True)

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            exited.append(True)

    monkeypatch.setattr(cli_app, "sigint_cancels", lambda token: FakeSigintScope())
    args = cli_app.build_parser().parse_args(
        ["--provider", "fake", "--prompt", "hello", "--events", "text"]
    )

    output = StringIO()
    assert cli_app.run_cli(args, output) == 0
    assert entered == [True]
    assert exited == [True]
    assert output.getvalue().splitlines() == [
        "[message] model/assistant: fake reply",
        '[state_update] model: {"status":"completed","error":null}',
    ]


def test_cli_consumes_all_modes_in_order_and_flushes_each_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _ScriptedGraph(
        [
            (
                "messages",
                (
                    AIMessageChunk(content="hel", id="token-1"),
                    {"langgraph_node": "model"},
                ),
            ),
            ("updates", {"tools": {"status": "ready", "tool_rounds": 1}}),
            (
                "custom",
                {
                    "type": "progress",
                    "node": "tools",
                    "message": "working",
                    "completed": 1,
                    "total": 2,
                },
            ),
            (
                "messages",
                (
                    AIMessageChunk(content="lo", id="token-2"),
                    {"langgraph_node": "model"},
                ),
            ),
            ("updates", {"model": {"status": "completed", "error": None}}),
        ]
    )
    monkeypatch.setattr(cli_app, "build_minimal_graph", lambda: graph)
    args = cli_app.build_parser().parse_args(
        ["--provider", "fake", "--prompt", "hello", "--events", "jsonl"]
    )
    output = _FlushTrackingOutput()

    assert cli_app.run_cli(args, output) == cli_app.EXIT_SUCCESS
    payloads = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [payload["kind"] for payload in payloads] == [
        "message",
        "tool",
        "progress",
        "message",
        "state_update",
    ]
    assert [payload["sequence"] for payload in payloads] == [0, 1, 2, 3, 4]
    assert [payloads[0]["payload"]["content"], payloads[3]["payload"]["content"]] == [
        "hel",
        "lo",
    ]
    assert graph.stream_mode == ["updates", "messages", "custom"]
    assert graph.closed
    assert output.flush_calls == len(payloads)


def test_cli_returns_failure_once_for_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_app,
        "FakeChatModel",
        lambda: FakeChatModel(error=RuntimeError("offline")),
    )
    args = cli_app.build_parser().parse_args(
        ["--provider", "fake", "--prompt", "hello", "--events", "jsonl"]
    )
    output = _FlushTrackingOutput()

    assert cli_app.run_cli(args, output) == cli_app.EXIT_FAILURE
    payloads = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [payload["kind"] for payload in payloads] == ["error"]
    assert payloads[0]["payload"]["status"] == "failed"
    assert output.flush_calls == 1


def test_cli_returns_failure_when_stream_ends_without_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _ScriptedGraph(
        [
            (
                "messages",
                (
                    AIMessageChunk(content="partial", id="token-1"),
                    {"langgraph_node": "model"},
                ),
            )
        ]
    )
    monkeypatch.setattr(cli_app, "build_minimal_graph", lambda: graph)
    args = cli_app.build_parser().parse_args(
        ["--provider", "fake", "--prompt", "hello", "--events", "text"]
    )
    output = _FlushTrackingOutput()

    assert cli_app.run_cli(args, output) == cli_app.EXIT_FAILURE
    assert output.getvalue().splitlines() == ["[message] model/assistant: partial"]
    assert graph.closed


def test_cli_returns_cancelled_when_sigint_scope_cancels_before_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancelOnEnter:
        def __init__(self, token: CancellationToken) -> None:
            self._token = token

        def __enter__(self) -> None:
            self._token.cancel()

        def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
            return None

    monkeypatch.setattr(cli_app, "sigint_cancels", CancelOnEnter)
    args = cli_app.build_parser().parse_args(
        ["--provider", "fake", "--prompt", "hello", "--events", "text"]
    )
    output = _FlushTrackingOutput()

    assert cli_app.run_cli(args, output) == cli_app.EXIT_CANCELLED
    assert output.getvalue() == ""
    assert output.flush_calls == 0


def test_cli_closes_raw_stream_when_output_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _ScriptedGraph(
        [
            (
                "messages",
                (
                    AIMessageChunk(content="hello", id="token-1"),
                    {"langgraph_node": "model"},
                ),
            )
        ]
    )
    monkeypatch.setattr(cli_app, "build_minimal_graph", lambda: graph)
    args = cli_app.build_parser().parse_args(
        ["--provider", "fake", "--prompt", "hello", "--events", "text"]
    )

    class FailingOutput(StringIO):
        def write(self, value: str) -> int:
            raise OSError("output unavailable")

    with pytest.raises(OSError, match="output unavailable"):
        cli_app.run_cli(args, FailingOutput())

    assert graph.closed
