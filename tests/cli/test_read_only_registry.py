"""Red tests for the learner-owned M8.8-R5 read-only tool registry."""

import json
from pathlib import Path

from langchain_core.messages import ToolCall

from pi_agent.cli.read_only import create_cli_read_only_registry


def test_cli_registry_contains_only_read_only_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    registry = create_cli_read_only_registry(workspace)

    assert [tool.name for tool in registry.tools] == ["read", "list", "search"]


def test_cli_registry_executes_read_list_and_search_in_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("LangGraph agent", encoding="utf-8")
    (workspace / "docs").mkdir()

    registry = create_cli_read_only_registry(workspace)

    read = registry.execute_call(_call("read", {"path": "README.md"}, "read-1"))
    listed = registry.execute_call(_call("list", {"path": "."}, "list-1"))
    searched = registry.execute_call(
        _call("search", {"query": "langgraph", "case_sensitive": False}, "search-1")
    )

    assert read.status == "success" and read.content == "LangGraph agent"
    assert listed.status == "success" and "file\tREADME.md" in str(listed.content)
    assert searched.status == "success" and "README.md:1:LangGraph agent" in str(searched.content)


def test_cli_registry_rejects_outside_paths_and_has_no_mutating_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("DO-NOT-LEAK", encoding="utf-8")
    registry = create_cli_read_only_registry(workspace)

    result = registry.execute_call(_call("read", {"path": "../secret.txt"}, "read-2"))

    assert result.status == "error"
    assert json.loads(str(result.content))["code"] == "tool_execution_error"
    assert registry.find("apply") is None
    assert registry.find("process") is None
    assert "DO-NOT-LEAK" not in str(result.content)


def _call(name: str, args: dict[str, object], call_id: str) -> ToolCall:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}
