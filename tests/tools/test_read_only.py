"""Read-only M4 tool contracts over a temporary workspace."""

import json
from pathlib import Path

import pytest
from langchain_core.messages import ToolCall

from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools import (
    TextOutputBudget,
    ToolRegistry,
    create_list_tool,
    create_read_tool,
    create_search_tool,
)


def test_read_returns_a_selected_text_window(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("one\ntwo\nthree\nfour", encoding="utf-8")
    tool = create_read_tool(WorkspacePathPolicy(workspace))

    result = tool.invoke({"path": "README.md", "offset": 2, "limit": 2})

    assert result == "two\nthree"


def test_read_rejects_a_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = create_read_tool(WorkspacePathPolicy(workspace))

    with pytest.raises(ValueError, match="must identify a file"):
        tool.invoke({"path": "."})


def test_list_returns_direct_children_in_stable_order(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "zeta.txt").write_text("z", encoding="utf-8")
    (workspace / "Alpha").mkdir()
    (workspace / "beta.txt").write_text("b", encoding="utf-8")
    tool = create_list_tool(WorkspacePathPolicy(workspace))

    result = tool.invoke({"path": "."})

    assert result.splitlines() == ["directory\tAlpha", "file\tbeta.txt", "file\tzeta.txt"]


def test_search_returns_workspace_relative_line_matches(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "docs"
    nested.mkdir()
    (workspace / "README.md").write_text("LangGraph agent\nother", encoding="utf-8")
    (nested / "notes.txt").write_text("using langgraph safely", encoding="utf-8")
    tool = create_search_tool(WorkspacePathPolicy(workspace))

    result = tool.invoke({"query": "langgraph", "path": ".", "case_sensitive": False})

    assert result.splitlines() == [
        "README.md:1:LangGraph agent",
        "docs/notes.txt:1:using langgraph safely",
    ]


def test_search_stops_at_the_match_limit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hit\nhit\nhit", encoding="utf-8")
    tool = create_search_tool(WorkspacePathPolicy(workspace), max_matches=2)

    result = tool.invoke({"query": "hit"})

    assert result.splitlines() == [
        "notes.txt:1:hit",
        "notes.txt:2:hit",
        "[Search stopped at match limit (2).]",
    ]


def test_read_output_is_bounded_before_registry_returns_it(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "large.txt").write_text("one\ntwo\nthree", encoding="utf-8")
    tool = create_read_tool(
        WorkspacePathPolicy(workspace),
        TextOutputBudget(max_lines=2, max_bytes=100),
    )

    result = tool.invoke({"path": "large.txt"})

    assert result.startswith("one\ntwo\n\n[Output truncated by lines:")


def test_registry_returns_an_error_without_reading_an_outside_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("DO-NOT-LEAK", encoding="utf-8")
    registry = ToolRegistry([create_read_tool(WorkspacePathPolicy(workspace))])

    result = registry.execute_call(_call("read", {"path": "../secret.txt"}, "call-read"))

    assert result.status == "error"
    assert result.tool_call_id == "call-read"
    assert _error_payload(result.content)["code"] == "tool_execution_error"
    assert "DO-NOT-LEAK" not in str(result.content)


def _call(name: str, args: dict[str, object], call_id: str) -> ToolCall:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _error_payload(content: str | list[str | dict[object, object]]) -> dict[object, object]:
    assert isinstance(content, str)
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload
