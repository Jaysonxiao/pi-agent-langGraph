"""Telemetry recorder: redact attributes, isolate sink failures, stay fail-open."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pi_agent.telemetry.ports import MetricsPort, StructuredLogPort
from pi_agent.telemetry.redaction import redact_attributes

TelemetrySinkName = Literal["metrics", "logs"]


@dataclass(frozen=True, slots=True)
class TelemetryFailure:
    """Sanitized sink failure; type only, never the exception message."""

    sink: TelemetrySinkName
    exception_type: str


@dataclass(slots=True)
class TelemetryRecorder:
    """Fan-out to optional metrics/log sinks without affecting Agent control flow."""

    metrics: MetricsPort | None = None
    logs: StructuredLogPort | None = None
    _failures: list[TelemetryFailure] = field(default_factory=list, init=False, repr=False)

    @property
    def failures(self) -> tuple[TelemetryFailure, ...]:
        """Return a detached snapshot of isolated sink failures."""
        return tuple(self._failures)

    def record_metric(
        self,
        name: str,
        value: float,
        /,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        """Record one metric after redaction; missing or failing sinks are skipped."""
        if self.metrics is None:
            return
        # 先脱敏再交给 sink, 后端即使原样落盘也拿不到明文密钥.
        sanitized = redact_attributes(attributes or {})
        try:
            self.metrics.record(name, value, sanitized)
        except Exception as exc:
            # CancelledError 不是 Exception; 普通 sink 故障只记类型名, 不打断主流程.
            self._failures.append(
                TelemetryFailure(sink="metrics", exception_type=type(exc).__name__)
            )

    def log_event(
        self,
        level: str,
        event: str,
        /,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        """Emit one structured event after redaction; sink errors stay isolated."""
        if self.logs is None:
            return
        sanitized = redact_attributes(attributes or {})
        try:
            self.logs.emit(level, event, sanitized)
        except Exception as exc:
            self._failures.append(TelemetryFailure(sink="logs", exception_type=type(exc).__name__))
