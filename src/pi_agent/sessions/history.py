"""Stable application projection of LangGraph checkpoint history."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast, get_args

from langgraph.types import StateSnapshot

from pi_agent.domain.state import RunStatus
from pi_agent.graph.builder import AgentGraph
from pi_agent.sessions.config import session_config


@dataclass(frozen=True, slots=True)
class SessionCheckpoint:
    """Framework-neutral checkpoint summary used by session history and fork."""

    checkpoint_id: str
    created_at: str
    source: str
    step: int
    status: RunStatus | None
    message_count: int
    next_nodes: tuple[str, ...]


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping.")
    return value


def _require_nonempty_str(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string.")
    return value


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an int.")
    return value


def _require_sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field} must be a sequence.")
    return value


def project_session_checkpoint(snapshot: StateSnapshot) -> SessionCheckpoint:
    """Project one LangGraph snapshot into the stable session-history contract."""
    config = _require_mapping(snapshot.config, "config")
    configurable = _require_mapping(config.get("configurable"), "configurable")
    checkpoint_id = _require_nonempty_str(configurable.get("checkpoint_id"), "checkpoint_id")
    created_at = _require_nonempty_str(snapshot.created_at, "created_at")

    metadata = _require_mapping(snapshot.metadata, "metadata")
    source = _require_nonempty_str(metadata.get("source"), "source")
    step = _require_int(metadata.get("step"), "step")

    values = _require_mapping(snapshot.values, "values")
    status = values.get("status")
    if status is not None and status not in get_args(RunStatus):
        raise ValueError("status must be a RunStatus or None.")
    messages = _require_sequence(values.get("messages"), "messages")
    next_nodes = tuple(_require_sequence(snapshot.next, "next"))

    return SessionCheckpoint(
        checkpoint_id=checkpoint_id,
        created_at=created_at,
        source=source,
        step=step,
        status=cast(RunStatus | None, status),
        message_count=len(messages),
        next_nodes=cast(tuple[str, ...], next_nodes),
    )


def list_session_checkpoints(graph: AgentGraph, session_id: str) -> list[SessionCheckpoint]:
    """Return checkpoint summaries in LangGraph's newest-first order."""
    return [
        project_session_checkpoint(snapshot)
        for snapshot in graph.get_state_history(session_config(session_id))
    ]
