"""Backend-agnostic telemetry span port; no SDK types leak into callers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

SpanOutcome = Literal["completed", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class SpanContext:
    """Trace/span identity shared with child spans; no payload fields."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None


class TelemetrySpan(Protocol):
    """Handle returned by start_span; end() records the terminal outcome."""

    @property
    def context(self) -> SpanContext:
        """Return the identity assigned at start."""
        ...

    def end(self, outcome: SpanOutcome, /) -> None:
        """Mark this span finished with a sanitized outcome."""
        ...


class TelemetryPort(Protocol):
    """Replaceable span backend; implementations must redact attributes first."""

    def start_span(
        self,
        name: str,
        /,
        *,
        attributes: Mapping[str, object] | None = None,
        parent: SpanContext | None = None,
    ) -> TelemetrySpan:
        """Open one span; root creates a trace, child inherits the parent trace."""
        ...


class MetricsPort(Protocol):
    """Replaceable metrics sink; recorder redacts attributes before record()."""

    def record(self, name: str, value: float, attributes: Mapping[str, object], /) -> None:
        """Accept one numeric sample with already-sanitized attributes."""
        ...


class StructuredLogPort(Protocol):
    """Replaceable structured logger; recorder redacts attributes before emit()."""

    def emit(
        self,
        level: str,
        event: str,
        attributes: Mapping[str, object],
        /,
    ) -> None:
        """Accept one log event with already-sanitized attributes."""
        ...
