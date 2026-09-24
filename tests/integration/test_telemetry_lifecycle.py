"""Integration tests for correlated spans across Provider lifecycle hooks."""

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import stream_provider_session
from pi_agent.events import StreamEvent
from pi_agent.extensions import HookDispatchResult, HookEvent, HookRegistry
from pi_agent.telemetry import (
    InMemoryTelemetry,
    SpanContext,
    SpanOutcome,
    TelemetrySpan,
)
from pi_agent.telemetry.lifecycle import TelemetryLifecycleHook


class ScriptedToolModel:
    def __init__(self) -> None:
        self._replies = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read",
                        "args": {"path": "probe.txt"},
                        "id": "read-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="A concise summary.", id="assistant-final"),
        ]

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        del messages, config
        return self._replies.pop(0)


def test_run_model_and_tool_spans_share_one_redacted_trace(tmp_path: Path) -> None:
    (tmp_path / "probe.txt").write_text("synthetic probe contents", encoding="utf-8")
    options = ProviderCliOptions(
        provider="fake",
        prompt="read probe.txt and summarize",
        events="jsonl",
        database=tmp_path / "telemetry.sqlite",
        session_id="telemetry-thread",
        workspace=tmp_path,
    )
    telemetry = InMemoryTelemetry()
    lifecycle_hook = TelemetryLifecycleHook(telemetry)
    hooks = HookRegistry()
    hooks.register("telemetry", lifecycle_hook.handle)

    async def scenario() -> None:
        async for _event in stream_provider_session(
            options,
            model=ScriptedToolModel(),
            message_id="user-1",
            hooks=hooks,
        ):
            pass

    asyncio.run(scenario())

    records = telemetry.records
    root = next(record for record in records if record.name == "agent.run")
    children = [record for record in records if record.name != "agent.run"]
    model_records = [record for record in children if record.name == "agent.model"]
    tool_records = [record for record in children if record.name == "agent.tool"]

    assert len(records) == 4
    assert len(model_records) == 2
    assert len(tool_records) == 1
    assert root.outcome == "completed"
    assert root.attributes["thread_id"] == options.session_id
    assert root.attributes["run_id"]
    assert all(record.outcome == "completed" for record in children)
    assert all(record.context.trace_id == root.context.trace_id for record in children)
    assert all(record.context.parent_span_id == root.context.span_id for record in children)
    assert tool_records[0].attributes["tool_name"] == "read"
    assert tool_records[0].attributes["tool_call_id"] == "read-1"
    assert "synthetic probe contents" not in repr(records)
    assert "read probe.txt and summarize" not in repr(records)


class BrokenTelemetry:
    def start_span(
        self,
        name: str,
        /,
        *,
        attributes: Mapping[str, object] | None = None,
        parent: SpanContext | None = None,
    ) -> TelemetrySpan:
        del name, attributes, parent
        raise RuntimeError("synthetic telemetry sink failure")


def test_telemetry_failure_does_not_fail_provider_run(tmp_path: Path) -> None:
    options = ProviderCliOptions(
        provider="fake",
        prompt="hello",
        events="jsonl",
        database=tmp_path / "telemetry-failure.sqlite",
        session_id="telemetry-failure-thread",
        workspace=tmp_path,
    )
    hooks = HookRegistry()
    hooks.register("telemetry", TelemetryLifecycleHook(BrokenTelemetry()).handle)

    class OneReplyModel:
        async def ainvoke(
            self,
            messages: Sequence[AnyMessage],
            config: RunnableConfig | None = None,
            /,
        ) -> AIMessage:
            del messages, config
            return AIMessage(content="done", id="assistant-done")

    async def scenario() -> list[StreamEvent]:
        events: list[StreamEvent] = []
        async for event in stream_provider_session(
            options,
            model=OneReplyModel(),
            message_id="user-1",
            hooks=hooks,
        ):
            events.append(event)
        return events

    events = asyncio.run(scenario())

    assert events
    assert events[-1].payload["status"] == "completed"


def test_run_end_closes_remaining_spans_when_one_child_end_fails() -> None:
    backend = InMemoryTelemetry()
    end_calls: list[str] = []

    class EndTrackingSpan:
        def __init__(self, name: str, inner: TelemetrySpan, *, fail_on_end: bool) -> None:
            self.name = name
            self._inner = inner
            self._fail_on_end = fail_on_end

        @property
        def context(self) -> SpanContext:
            return self._inner.context

        def end(self, outcome: SpanOutcome, /) -> None:
            end_calls.append(self.name)
            if self._fail_on_end:
                raise RuntimeError("synthetic span end failure")
            self._inner.end(outcome)

    class EndTrackingTelemetry:
        def start_span(
            self,
            name: str,
            /,
            *,
            attributes: Mapping[str, object] | None = None,
            parent: SpanContext | None = None,
        ) -> TelemetrySpan:
            inner = backend.start_span(name, attributes=attributes, parent=parent)
            return EndTrackingSpan(name, inner, fail_on_end=name == "agent.model")

    lifecycle_hook = TelemetryLifecycleHook(EndTrackingTelemetry())
    hooks = HookRegistry()
    hooks.register("telemetry", lifecycle_hook.handle)

    async def scenario() -> HookDispatchResult:
        await hooks.dispatch(
            HookEvent(phase="run_start", thread_id="thread-1", run_id="run-1", sequence=0)
        )
        await hooks.dispatch(
            HookEvent(
                phase="before_model",
                thread_id="thread-1",
                run_id="run-1",
                sequence=1,
                node="model",
            )
        )
        await hooks.dispatch(
            HookEvent(
                phase="before_tool",
                thread_id="thread-1",
                run_id="run-1",
                sequence=2,
                node="tools",
                tool_name="read",
                tool_call_id="read-1",
            )
        )
        return await hooks.dispatch(
            HookEvent(
                phase="run_end",
                thread_id="thread-1",
                run_id="run-1",
                sequence=3,
                outcome="completed",
            )
        )

    dispatch = asyncio.run(scenario())

    assert end_calls == ["agent.model", "agent.tool", "agent.run"]
    assert [(failure.phase, failure.exception_type) for failure in dispatch.failures] == [
        ("run_end", "RuntimeError")
    ]
    # 内存后端按创建顺序记录,root 先于 child;按名称断言避免依赖记录顺序。
    outcomes_by_name = {record.name: record.outcome for record in backend.records}
    assert outcomes_by_name == {
        "agent.run": "completed",
        "agent.model": None,
        "agent.tool": "completed",
    }
