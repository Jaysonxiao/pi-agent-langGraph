"""Red tests for the learner-owned M9.3.5 metrics/log sink boundary."""

from collections.abc import Mapping

from pi_agent.telemetry.recorder import TelemetryRecorder


class RecordingMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float, Mapping[str, object]]] = []

    def record(self, name: str, value: float, attributes: Mapping[str, object], /) -> None:
        self.calls.append((name, value, dict(attributes)))


class RecordingLogs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, object]]] = []

    def emit(
        self,
        level: str,
        event: str,
        attributes: Mapping[str, object],
        /,
    ) -> None:
        self.calls.append((level, event, dict(attributes)))


class FailingMetrics:
    def record(self, name: str, value: float, attributes: Mapping[str, object], /) -> None:
        del name, value, attributes
        raise RuntimeError("metrics backend rejected synthetic-secret")


class FailingLogs:
    def emit(
        self,
        level: str,
        event: str,
        attributes: Mapping[str, object],
        /,
    ) -> None:
        del level, event, attributes
        raise OSError("logger backend failed with private-prompt")


def test_metrics_and_logs_receive_redacted_attributes() -> None:
    metrics = RecordingMetrics()
    logs = RecordingLogs()
    recorder = TelemetryRecorder(metrics=metrics, logs=logs)

    recorder.record_metric(
        "agent.run.count",
        1,
        attributes={"run_id": "run-1", "api_key": "synthetic-secret"},
    )
    recorder.log_event(
        "info",
        "agent.run.completed",
        attributes={"thread_id": "thread-1", "prompt": "private prompt"},
    )

    assert metrics.calls == [("agent.run.count", 1, {"run_id": "run-1", "api_key": "[REDACTED]"})]
    assert logs.calls == [
        (
            "info",
            "agent.run.completed",
            {"thread_id": "thread-1", "prompt": "[REDACTED]"},
        )
    ]
    assert recorder.failures == ()


def test_sink_failures_are_isolated_and_sanitized() -> None:
    logs = RecordingLogs()
    recorder = TelemetryRecorder(metrics=FailingMetrics(), logs=logs)

    recorder.record_metric("agent.run.count", 1, attributes={"run_id": "run-2"})
    recorder.log_event("info", "agent.run.completed", attributes={"run_id": "run-2"})

    assert logs.calls == [("info", "agent.run.completed", {"run_id": "run-2"})]
    assert len(recorder.failures) == 1
    assert recorder.failures[0].sink == "metrics"
    assert recorder.failures[0].exception_type == "RuntimeError"
    assert "synthetic-secret" not in repr(recorder.failures)


def test_each_sink_failure_is_recorded_without_leaking_its_message() -> None:
    recorder = TelemetryRecorder(metrics=FailingMetrics(), logs=FailingLogs())

    recorder.record_metric("agent.run.count", 1)
    recorder.log_event("info", "agent.run.completed")

    assert [(failure.sink, failure.exception_type) for failure in recorder.failures] == [
        ("metrics", "RuntimeError"),
        ("logs", "OSError"),
    ]
    assert "synthetic-secret" not in repr(recorder.failures)
    assert "private-prompt" not in repr(recorder.failures)
