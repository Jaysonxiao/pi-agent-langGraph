"""Composition adapters that connect provider lifecycle hooks to local sinks."""

from dataclasses import dataclass, field

from pi_agent.extensions import HookEvent
from pi_agent.telemetry.jsonl import JsonlTelemetrySink
from pi_agent.telemetry.lifecycle import TelemetryLifecycleHook
from pi_agent.telemetry.recorder import TelemetryRecorder


@dataclass(slots=True)
class CliTelemetryHook:
    """Record spans, low-cardinality phase counts, and safe lifecycle metadata."""

    sink: JsonlTelemetrySink
    _lifecycle: TelemetryLifecycleHook = field(init=False, repr=False)
    _recorder: TelemetryRecorder = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lifecycle = TelemetryLifecycleHook(self.sink)
        self._recorder = TelemetryRecorder(metrics=self.sink, logs=self.sink)

    async def handle(self, event: HookEvent) -> None:
        """Observe one existing hook; sink errors are isolated by HookRegistry."""
        await self._lifecycle.handle(event)
        outcome = event.outcome or "active"
        self._recorder.record_metric(
            "agent.lifecycle.events",
            1.0,
            attributes={"phase": event.phase, "outcome": outcome},
        )
        attributes: dict[str, object] = {
            "thread_id": event.thread_id,
            "run_id": event.run_id,
            "phase": event.phase,
            "outcome": outcome,
        }
        if event.tool_name is not None:
            attributes["tool_name"] = event.tool_name
        if event.tool_call_id is not None:
            attributes["tool_call_id"] = event.tool_call_id
        self._recorder.log_event("INFO", "agent.lifecycle", attributes=attributes)
