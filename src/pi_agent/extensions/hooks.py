"""Typed, observation-only lifecycle hooks for the M9.1 learning slice.

The first M9 slice deliberately exposes correlation metadata rather than prompts,
tool arguments, model replies, or tool output.  Hook handlers are injected by the
application; this module does not discover or import third-party Python code.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

HookPhase = Literal[
    "run_start",
    "before_model",
    "after_model",
    "before_tool",
    "after_tool",
    "run_end",
]
HookOutcome = Literal["completed", "failed", "cancelled"]
HookHandler = Callable[["HookEvent"], Awaitable[None]]

_TOOL_PHASES: frozenset[HookPhase] = frozenset({"before_tool", "after_tool"})
_OUTCOME_PHASES: frozenset[HookPhase] = frozenset({"after_model", "after_tool", "run_end"})


def _require_identifier(value: str, field_name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-blank, trimmed string.")


@dataclass(frozen=True, slots=True)
class HookEvent:
    """Secret-free lifecycle metadata shared with one registered hook."""

    phase: HookPhase
    thread_id: str
    run_id: str
    sequence: int
    node: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    outcome: HookOutcome | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.thread_id, "thread_id")
        _require_identifier(self.run_id, "run_id")
        if self.sequence < 0:
            raise ValueError("sequence must be zero or greater.")
        if self.node is not None:
            _require_identifier(self.node, "node")

        tool_identity = (self.tool_name, self.tool_call_id)
        if self.phase in _TOOL_PHASES:
            if any(value is None for value in tool_identity):
                raise ValueError("tool hooks require tool_name and tool_call_id.")
            _require_identifier(self.tool_name or "", "tool_name")
            _require_identifier(self.tool_call_id or "", "tool_call_id")
        elif any(value is not None for value in tool_identity):
            raise ValueError("non-tool hooks must not include tool identity.")

        if self.outcome is not None and self.phase not in _OUTCOME_PHASES:
            raise ValueError("outcome is only valid for after_model, after_tool, or run_end.")


@dataclass(frozen=True, slots=True)
class HookFailure:
    """Sanitized hook failure suitable for telemetry and eval artifacts."""

    hook_name: str
    phase: HookPhase
    exception_type: str


@dataclass(frozen=True, slots=True)
class HookDispatchResult:
    """All isolated ordinary failures from one lifecycle phase."""

    failures: tuple[HookFailure, ...] = ()


@dataclass(frozen=True, slots=True)
class _RegisteredHook:
    name: str
    handler: HookHandler


class HookRegistry:
    """Registration-ordered hook table; handlers cannot mutate graph state."""

    def __init__(self) -> None:
        self._hooks: list[_RegisteredHook] = []
        self._names: set[str] = set()

    @property
    def names(self) -> tuple[str, ...]:
        """Return a detached registration-order view."""
        return tuple(hook.name for hook in self._hooks)

    def register(self, name: str, handler: HookHandler, /) -> None:
        """Register one application-owned async handler under a unique name."""
        _require_identifier(name, "name")
        if name in self._names:
            raise ValueError(f"Duplicate hook name: {name}")
        self._hooks.append(_RegisteredHook(name=name, handler=handler))
        self._names.add(name)

    async def dispatch(self, event: HookEvent, /) -> HookDispatchResult:
        """Run a snapshot of handlers in order and report sanitized failures."""
        # 只遍历派发开始时的副本, 本次 await 期间新 register 的 handler 不进入本轮.
        snapshot = tuple(self._hooks)
        failures: list[HookFailure] = []
        for hook in snapshot:
            try:
                await hook.handler(event)
            except Exception as exc:
                # CancelledError 不是 Exception, 会原样冒泡并停止后续 handler.
                # 只保留类型名, 避免把异常正文里的密钥带进 telemetry/eval.
                failures.append(
                    HookFailure(
                        hook_name=hook.name,
                        phase=event.phase,
                        exception_type=type(exc).__name__,
                    )
                )
        return HookDispatchResult(failures=tuple(failures))
