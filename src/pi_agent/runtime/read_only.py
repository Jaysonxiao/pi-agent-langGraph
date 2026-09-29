"""Shared read-only workspace tool assembly for CLI and server runtimes."""

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


class ReadOnlyWorkspacePathPolicy(WorkspacePathPolicy):
    """Hide credentials and runtime internals from provider-visible tools."""

    def resolve(self, requested_path: str, *, must_exist: bool = True) -> Path:
        target = super().resolve(requested_path, must_exist=must_exist)
        for part in target.relative_to(self.root).parts:
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


@dataclass(frozen=True, slots=True)
class AsyncReadOnlyTool:
    """Adapt bounded synchronous file tools without blocking the event loop."""

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


def create_read_only_definitions(
    workspace: Path, *, output: TextOutputBudget | None = None
) -> tuple[ExecutableTool, ...]:
    """Build only workspace-confined read/list/search tool definitions."""
    paths = ReadOnlyWorkspacePathPolicy(workspace)
    return (
        create_read_tool(paths, output),
        create_list_tool(paths, output),
        create_search_tool(paths, output),
    )


def create_async_read_only_registry(
    workspace: Path,
    *,
    enabled_tools: tuple[str, ...] | None = None,
) -> tuple[AsyncToolRegistry, tuple[ExecutableTool, ...]]:
    available = create_read_only_definitions(workspace)
    if enabled_tools is None:
        definitions = available
    else:
        by_name = {tool.name: tool for tool in available}
        unknown = set(enabled_tools).difference(by_name)
        if unknown:
            raise ValueError(f"Unknown read-only tools: {', '.join(sorted(unknown))}")
        definitions = tuple(by_name[name] for name in enabled_tools)
    return AsyncToolRegistry(AsyncReadOnlyTool(tool) for tool in definitions), definitions


def create_sync_read_only_registry(
    workspace: Path, *, output: TextOutputBudget | None = None
) -> ToolRegistry:
    return ToolRegistry(create_read_only_definitions(workspace, output=output))
