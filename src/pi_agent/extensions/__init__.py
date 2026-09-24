"""Constrained lifecycle hooks for application-owned extensions."""

from pi_agent.extensions.hooks import (
    HookDispatchResult,
    HookEvent,
    HookFailure,
    HookHandler,
    HookOutcome,
    HookPhase,
    HookRegistry,
)

__all__ = [
    "HookDispatchResult",
    "HookEvent",
    "HookFailure",
    "HookHandler",
    "HookOutcome",
    "HookPhase",
    "HookRegistry",
]
