"""将 Provider 生命周期 hook 转换为后端无关的 telemetry spans。"""

from __future__ import annotations

from dataclasses import dataclass, field

from pi_agent.extensions.hooks import HookEvent
from pi_agent.telemetry.ports import SpanOutcome, TelemetryPort, TelemetrySpan


@dataclass(slots=True)
class TelemetryLifecycleHook:
    """按 run 管理 root/child span;只记录关联标识,不接触请求正文。"""

    telemetry: TelemetryPort
    _roots: dict[str, TelemetrySpan] = field(default_factory=dict, init=False, repr=False)
    _children: dict[tuple[str, str, str], TelemetrySpan] = field(
        default_factory=dict, init=False, repr=False
    )

    async def handle(self, event: HookEvent) -> None:
        """消费一个 lifecycle 事件;缺失或重复配对时安全忽略。"""
        if event.phase == "run_start":
            # 重复 start 不覆盖已有 span,避免遗失尚未结束的 run root。
            if event.run_id not in self._roots:
                self._roots[event.run_id] = self.telemetry.start_span(
                    "agent.run",
                    attributes={"thread_id": event.thread_id, "run_id": event.run_id},
                )
            return

        if event.phase in {"before_model", "before_tool"}:
            root = self._roots.get(event.run_id)
            if root is None:
                return
            is_tool = event.phase == "before_tool"
            identity = event.tool_call_id if is_tool else (event.node or "model")
            if identity is None:
                return
            key = (event.run_id, "tool" if is_tool else "model", identity)
            if key in self._children:
                return
            attributes: dict[str, object] = {"thread_id": event.thread_id, "run_id": event.run_id}
            if is_tool:
                attributes.update(
                    {"tool_name": event.tool_name or "", "tool_call_id": event.tool_call_id or ""}
                )
            self._children[key] = self.telemetry.start_span(
                "agent.tool" if is_tool else "agent.model",
                attributes=attributes,
                parent=root.context,
            )
            return

        if event.phase in {"after_model", "after_tool"}:
            is_tool = event.phase == "after_tool"
            identity = event.tool_call_id if is_tool else (event.node or "model")
            if identity is None:
                return
            key = (event.run_id, "tool" if is_tool else "model", identity)
            span = self._children.pop(key, None)
            if span is not None:
                span.end(event.outcome or "completed")
            return

        if event.phase == "run_end":
            outcome: SpanOutcome = event.outcome or "failed"
            # run_end 也負責收尾未配對的 child,避免异常或缺失 after 事件留下悬挂 span。
            first_error: Exception | None = None
            for key in tuple(self._children):
                if key[0] == event.run_id:
                    span = self._children.pop(key)
                    try:
                        span.end(outcome)
                    except Exception as exc:
                        # 一个 span 结束失败时仍继续清理其他 child 和 root。
                        if first_error is None:
                            first_error = exc
            root = self._roots.pop(event.run_id, None)
            if root is not None:
                try:
                    root.end(outcome)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
            if first_error is not None:
                # 所有 span 都尝试收尾后再交给 HookRegistry 记录脱敏失败类型。
                raise first_error
