"""Explicit provider CLI options for the M8.8 runtime assembly."""

from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

ProviderName = Literal["fake", "compatible"]
EventMode = Literal["text", "jsonl"]

_PROVIDERS: frozenset[str] = frozenset({"fake", "compatible"})
_EVENT_MODES: frozenset[str] = frozenset({"text", "jsonl"})


@dataclass(frozen=True, slots=True)
class ProviderCliOptions:
    """Non-secret runtime options passed from the CLI boundary."""

    provider: ProviderName
    prompt: str
    events: EventMode
    database: Path
    session_id: str
    workspace: Path


def resolve_provider_cli_options(args: Namespace) -> ProviderCliOptions:
    """Validate and project parsed CLI arguments without reading global state."""
    # 只读传入 Namespace, 不碰 os.environ, 也不把 api_key 拷进 DTO.
    provider = getattr(args, "provider", None)
    prompt = getattr(args, "prompt", None)
    events = getattr(args, "events", None)
    database = getattr(args, "database", None)
    session_id = getattr(args, "session_id", None)
    workspace = getattr(args, "workspace", None)

    if provider not in _PROVIDERS:
        raise ValueError("Provider must be 'fake' or 'compatible'.")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must not be blank.")
    if events not in _EVENT_MODES:
        raise ValueError("Events must be 'text' or 'jsonl'.")
    if not isinstance(database, Path):
        raise ValueError("Database path is required.")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Session id is required.")
    if not isinstance(workspace, Path):
        raise ValueError("Workspace path is required.")

    return ProviderCliOptions(
        provider=cast(ProviderName, provider),
        prompt=prompt,
        events=cast(EventMode, events),
        database=database,
        session_id=session_id,
        workspace=workspace,
    )
