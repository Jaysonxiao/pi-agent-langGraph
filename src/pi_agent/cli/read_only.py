"""Minimal read-only tool registry for the M8.8 CLI runtime."""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from pi_agent.security import PathPolicyError, WorkspacePathPolicy
from pi_agent.tools import (
    TextOutputBudget,
    ToolRegistry,
    create_list_tool,
    create_read_tool,
    create_search_tool,
)
from pi_agent.tools.async_registry import AsyncToolRegistry
from pi_agent.tools.base import ExecutableTool
from pi_agent.tools.command_approval import create_command_proposal_tool


class CliWorkspacePathPolicy(WorkspacePathPolicy):
    """Exclude local credentials and runtime internals from provider-visible tools."""

    def resolve(self, requested_path: str, *, must_exist: bool = True) -> Path:
        target = super().resolve(requested_path, must_exist=must_exist)
        relative = target.relative_to(self.root)
        for part in relative.parts:
            lowered = part.casefold()
            if (
                (lowered.startswith(".env") and lowered != ".env.example")
                or lowered in {".git", ".venv", "__pycache__", "credentials.json"}
                or lowered.startswith(".pytest-tmp")
                or lowered.endswith((".pem", ".key"))
            ):
                raise PathPolicyError(
                    "invalid_path",
                    requested_path,
                    "Sensitive path is unavailable to provider tools.",
                )
        return target


def create_cli_read_only_registry(
    workspace: Path,
    *,
    output: TextOutputBudget | None = None,
) -> ToolRegistry:
    """Create only workspace-confined read/list/search tools."""
    # 显式工作区策略, 不注册 apply/process, 也不绕过输出预算.
    paths = CliWorkspacePathPolicy(workspace)
    return ToolRegistry(
        (
            create_read_tool(paths, output),
            create_list_tool(paths, output),
            create_search_tool(paths, output),
        )
    )


@dataclass(frozen=True, slots=True)
class AsyncCliTool:
    """Run a validated CLI tool handler without blocking the async graph."""

    delegate: ExecutableTool

    @property
    def name(self) -> str:
        return self.delegate.name

    @property
    def description(self) -> str:
        return self.delegate.description

    @property
    def args_schema(self) -> type[BaseModel]:
        return self.delegate.args_schema

    async def ainvoke(self, raw_args: Mapping[str, object]) -> str:
        return await asyncio.to_thread(self.delegate.invoke, raw_args)


def create_cli_async_read_only_registry(
    workspace: Path,
    *,
    database: Path | None = None,
    session_id: str | None = None,
    allowed_executables: frozenset[str] = frozenset(),
) -> tuple[AsyncToolRegistry, tuple[ExecutableTool, ...]]:
    """Return read-only tools plus an optional non-executing command proposal."""
    definitions = create_cli_read_only_registry(workspace).tools
    if allowed_executables:
        if database is None or session_id is None:
            raise ValueError("Command proposals require a durable database and session id.")
        definitions = (
            *definitions,
            create_command_proposal_tool(
                database,
                session_id=session_id,
                workspace=WorkspacePathPolicy(workspace),
                allowed_executables=allowed_executables,
            ),
        )
    return AsyncToolRegistry(AsyncCliTool(tool) for tool in definitions), definitions
