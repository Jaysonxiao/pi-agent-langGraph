"""In-memory TelemetryPort for tests; stores redacted parent/child spans."""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import uuid4

from pi_agent.telemetry.ports import SpanContext, SpanOutcome, TelemetrySpan
from pi_agent.telemetry.redaction import redact_attributes


@dataclass(slots=True)
class SpanRecord:
    """One recorded span; attributes are already redacted at start time."""

    name: str
    context: SpanContext
    attributes: dict[str, object]
    outcome: SpanOutcome | None = None


class _InMemorySpan:
    """Handle that writes outcome back onto the stored record."""

    def __init__(self, record: SpanRecord) -> None:
        self._record = record

    @property
    def context(self) -> SpanContext:
        return self._record.context

    def end(self, outcome: SpanOutcome, /) -> None:
        # 只记终态, 不再改 attributes, 避免 end 路径把明文写回去.
        self._record.outcome = outcome


class InMemoryTelemetry:
    """Test sink: records are appended on start, in creation order."""

    def __init__(self) -> None:
        self._records: list[SpanRecord] = []

    @property
    def records(self) -> tuple[SpanRecord, ...]:
        """Return a detached view; callers cannot append to the live list."""
        return tuple(self._records)

    def start_span(
        self,
        name: str,
        /,
        *,
        attributes: Mapping[str, object] | None = None,
        parent: SpanContext | None = None,
    ) -> TelemetrySpan:
        if parent is None:
            # 每个 root 开一条新 trace; child 必须复用 parent.trace_id.
            context = SpanContext(trace_id=uuid4().hex, span_id=uuid4().hex)
        else:
            context = SpanContext(
                trace_id=parent.trace_id,
                span_id=uuid4().hex,
                parent_span_id=parent.span_id,
            )
        # 进入 adapter 之前脱敏, 内存记录里不应留下 prompt / tool_args.
        record = SpanRecord(
            name=name,
            context=context,
            attributes=redact_attributes(attributes or {}),
        )
        self._records.append(record)
        return _InMemorySpan(record)
