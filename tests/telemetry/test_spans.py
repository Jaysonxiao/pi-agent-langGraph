"""Red tests for the learner-owned M9.3.4 telemetry span port."""

from pi_agent.telemetry.memory import InMemoryTelemetry


def test_records_root_and_child_spans_with_shared_trace_identity() -> None:
    telemetry = InMemoryTelemetry()

    run = telemetry.start_span("run", attributes={"thread_id": "thread-1", "run_id": "run-1"})
    model = telemetry.start_span(
        "model",
        attributes={"node": "model", "prompt": "private prompt"},
        parent=run.context,
    )
    model.end("completed")
    run.end("completed")

    run_record, model_record = telemetry.records
    assert run_record.context.parent_span_id is None
    assert model_record.context.trace_id == run_record.context.trace_id
    assert model_record.context.parent_span_id == run_record.context.span_id
    assert model_record.context.span_id != run_record.context.span_id
    assert model_record.outcome == run_record.outcome == "completed"
    assert model_record.attributes == {"node": "model", "prompt": "[REDACTED]"}


def test_separate_roots_create_distinct_traces_and_redact_tool_attributes() -> None:
    telemetry = InMemoryTelemetry()

    first = telemetry.start_span(
        "run",
        attributes={"thread_id": "thread-1", "tool_args": {"path": "private.txt"}},
    )
    second = telemetry.start_span("run", attributes={"thread_id": "thread-2"})
    first.end("failed")
    second.end("completed")

    first_record, second_record = telemetry.records
    assert first_record.context.trace_id != second_record.context.trace_id
    assert first_record.attributes["tool_args"] == "[REDACTED]"
    assert first_record.outcome == "failed"
    assert second_record.outcome == "completed"
