"""Opt-in content-free JSONL sink for a local CLI telemetry file."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from uuid import uuid4

from pi_agent.telemetry.ports import (
    MetricsPort,
    SpanContext,
    SpanOutcome,
    StructuredLogPort,
    TelemetryPort,
    TelemetrySpan,
)
from pi_agent.telemetry.redaction import redact_attributes


class _JsonlSpan:
    """Append a content-free terminal record for one opened span."""

    def __init__(self, sink: JsonlTelemetrySink, name: str, context: SpanContext) -> None:
        self._sink = sink
        self._name = name
        self._context = context
        self._ended = False

    @property
    def context(self) -> SpanContext:
        return self._context

    def end(self, outcome: SpanOutcome, /) -> None:
        if self._ended:
            return
        self._ended = True
        self._sink._append(
            {
                "kind": "span_finished",
                "name": self._name,
                "trace_id": self._context.trace_id,
                "span_id": self._context.span_id,
                "parent_span_id": self._context.parent_span_id,
                "outcome": outcome,
            }
        )


@dataclass(frozen=True, slots=True)
class JsonlTelemetrySink(TelemetryPort, MetricsPort, StructuredLogPort):
    """Append small redacted records; select it only through an explicit CLI option.

    Each record is opened and closed separately to avoid holding a file handle
    through model/tool execution or process shutdown.
    """

    path: Path

    def start_span(
        self,
        name: str,
        /,
        *,
        attributes: Mapping[str, object] | None = None,
        parent: SpanContext | None = None,
    ) -> TelemetrySpan:
        context = SpanContext(
            trace_id=parent.trace_id if parent is not None else uuid4().hex,
            span_id=uuid4().hex,
            parent_span_id=parent.span_id if parent is not None else None,
        )
        self._append(
            {
                "kind": "span_started",
                "name": name,
                "trace_id": context.trace_id,
                "span_id": context.span_id,
                "parent_span_id": context.parent_span_id,
                "attributes": dict(attributes or {}),
            }
        )
        return _JsonlSpan(self, name, context)

    def record(self, name: str, value: float, attributes: Mapping[str, object], /) -> None:
        if not isfinite(value):
            raise ValueError("Telemetry metric value must be finite.")
        self._append({"kind": "metric", "name": name, "value": value, "attributes": attributes})

    def emit(
        self,
        level: str,
        event: str,
        attributes: Mapping[str, object],
        /,
    ) -> None:
        self._append({"kind": "log", "level": level, "event": event, "attributes": attributes})

    def _append(self, record: Mapping[str, object]) -> None:
        safe_record = redact_attributes(record)
        line = json.dumps(
            safe_record,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(line + "\n")
