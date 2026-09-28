"""Compatibility wrappers for the shared read-only runtime tool assembly."""

from pathlib import Path

from pi_agent.runtime.read_only import (
    AsyncReadOnlyTool,
    ReadOnlyWorkspacePathPolicy,
    create_read_only_definitions,
    create_sync_read_only_registry,
)
from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools import TextOutputBudget, ToolRegistry
from pi_agent.tools.async_registry import AsyncToolRegistry
from pi_agent.tools.base import ExecutableTool
from pi_agent.tools.command_approval import create_command_proposal_tool

CliWorkspacePathPolicy = ReadOnlyWorkspacePathPolicy
AsyncCliTool = AsyncReadOnlyTool


def create_cli_read_only_registry(
    workspace: Path, *, output: TextOutputBudget | None = None
) -> ToolRegistry:
    """Keep the established CLI entry point over shared tool assembly."""
    return create_sync_read_only_registry(workspace, output=output)


def create_cli_async_read_only_registry(
    workspace: Path,
    *,
    database: Path | None = None,
    session_id: str | None = None,
    allowed_executables: frozenset[str] = frozenset(),
) -> tuple[AsyncToolRegistry, tuple[ExecutableTool, ...]]:
    """Preserve CLI-only durable command proposal registration."""
    definitions = create_read_only_definitions(workspace)
    if allowed_executables:
        if database is None or session_id is None:
            raise ValueError("Command proposals require a durable database and session id.")
        proposal = create_command_proposal_tool(
            database,
            session_id=session_id,
            workspace=WorkspacePathPolicy(workspace),
            allowed_executables=allowed_executables,
        )
        definitions = (*definitions, proposal)
    return AsyncToolRegistry(AsyncReadOnlyTool(tool) for tool in definitions), definitions
