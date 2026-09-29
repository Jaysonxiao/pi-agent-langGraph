"""M7.1 contracts for deterministic workspace instruction discovery."""

from pathlib import Path

import pytest

from pi_agent.context import discover_workspace_instruction_files
from pi_agent.security import PathPolicyError, WorkspacePathPolicy


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path.resolve(strict=True)


def test_discovery_returns_only_active_ancestor_rules_from_root_to_leaf(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    active_file = _write(workspace / "packages" / "agent" / "src" / "main.py", "pass\n")
    root_rules = _write(workspace / "AGENTS.md", "root")
    package_rules = _write(workspace / "packages" / "AGENTS.md", "packages")
    agent_rules = _write(workspace / "packages" / "agent" / "AGENTS.md", "agent")
    _write(workspace / "packages" / "sibling" / "AGENTS.md", "sibling")
    _write(workspace / "unrelated" / "AGENTS.md", "unrelated")

    discovered = discover_workspace_instruction_files(
        WorkspacePathPolicy(workspace),
        str(active_file),
    )

    assert discovered == (root_rules, package_rules, agent_rules)


def test_discovery_includes_rules_in_an_active_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    active_directory = workspace / "src" / "pi_agent"
    active_directory.mkdir(parents=True)
    root_rules = _write(workspace / "AGENTS.md", "root")
    active_rules = _write(active_directory / "AGENTS.md", "active")

    discovered = discover_workspace_instruction_files(
        WorkspacePathPolicy(workspace),
        str(active_directory),
    )

    assert discovered == (root_rules, active_rules)


def test_pi_instruction_discovery_ignores_codex_agents_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    active_file = _write(workspace / "src" / "main.py", "pass\n")
    _write(workspace / "AGENTS.md", "codex rules")
    root_pi_rules = _write(workspace / "PI-AGENTS.md", "pi root rules")
    leaf_pi_rules = _write(workspace / "src" / "PI-AGENTS.md", "pi leaf rules")

    discovered = discover_workspace_instruction_files(
        WorkspacePathPolicy(workspace), str(active_file), "PI-AGENTS.md"
    )

    assert discovered == (root_pi_rules, leaf_pi_rules)


def test_discovery_returns_empty_when_no_ancestor_has_rules(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    active_file = _write(workspace / "src" / "main.py", "pass\n")

    assert (
        discover_workspace_instruction_files(WorkspacePathPolicy(workspace), str(active_file)) == ()
    )


def test_discovery_rejects_an_active_path_outside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = _write(tmp_path / "outside.py", "pass\n")

    with pytest.raises(PathPolicyError) as captured:
        discover_workspace_instruction_files(WorkspacePathPolicy(workspace), str(outside))

    assert captured.value.code == "outside_workspace"
