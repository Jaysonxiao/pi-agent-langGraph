"""Content-free local telemetry sink contracts."""

import json
from pathlib import Path

import pytest

from pi_agent.telemetry.jsonl import JsonlTelemetrySink


def test_sink_records_parented_spans_metrics_and_logs_without_sensitive_values(
    tmp_path: Path,
) -> None:
    target = tmp_path / "telemetry.jsonl"
    sink = JsonlTelemetrySink(target)
    root = sink.start_span(
        "agent.run",
        attributes={
            "thread_id": "thread-1",
            "api_key": "synthetic-secret",
            "prompt": "synthetic prompt",
            "nested": {"content": "private content"},
        },
    )
    child = sink.start_span(
        "agent.tool",
        attributes={"tool_name": "read", "tool_output": "private output"},
        parent=root.context,
    )
    child.end("completed")
    child.end("completed")
    root.end("completed")
    sink.record("agent.lifecycle.events", 1.0, {"phase": "run_end"})
    sink.emit(
        "INFO",
        "agent.lifecycle",
        {"run_id": "run-1", "tool_name": "read", "authorization": "private"},
    )

    lines = target.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 6
    assert [record["kind"] for record in records] == [
        "span_started",
        "span_started",
        "span_finished",
        "span_finished",
        "metric",
        "log",
    ]
    assert records[1]["trace_id"] == records[0]["trace_id"]
    assert records[1]["parent_span_id"] == records[0]["span_id"]
    assert records[2]["outcome"] == records[3]["outcome"] == "completed"
    assert "synthetic-secret" not in "\n".join(lines)
    assert "synthetic prompt" not in "\n".join(lines)
    assert "private content" not in "\n".join(lines)
    assert "private output" not in "\n".join(lines)
    assert '"[REDACTED]"' in "\n".join(lines)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_sink_rejects_non_finite_metric_values(tmp_path: Path, value: float) -> None:
    sink = JsonlTelemetrySink(tmp_path / "telemetry.jsonl")

    with pytest.raises(ValueError, match="finite"):
        sink.record("agent.test", value, {})

    assert not sink.path.exists()
