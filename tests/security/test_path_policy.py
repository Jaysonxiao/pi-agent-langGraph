"""Contract tests for the M4 workspace path boundary."""

import os
import subprocess
from pathlib import Path

import pytest

from pi_agent.security import PathPolicyError, WorkspacePathPolicy


def _create_directory_link(target: Path, link: Path) -> None:
    """Create a real link on POSIX or an unprivileged directory junction on Windows."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise

    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"Could not create the Windows junction used by this security test: {completed.stderr}"
        )


def test_policy_canonicalizes_the_workspace_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    policy = WorkspacePathPolicy(workspace / ".")

    assert policy.root == workspace.resolve(strict=True)


def test_resolve_returns_an_existing_relative_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "README.md"
    target.write_text("hello", encoding="utf-8")
    policy = WorkspacePathPolicy(workspace)

    assert policy.resolve("README.md") == target.resolve(strict=True)


def test_resolve_accepts_an_absolute_path_only_when_it_is_inside_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("safe", encoding="utf-8")
    policy = WorkspacePathPolicy(workspace)

    assert policy.resolve(str(target)) == target.resolve(strict=True)


@pytest.mark.parametrize("requested_path", ["", "   ", "bad\x00path"])
def test_resolve_rejects_invalid_model_paths(tmp_path: Path, requested_path: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = WorkspacePathPolicy(workspace)

    with pytest.raises(PathPolicyError) as captured:
        policy.resolve(requested_path)

    assert captured.value.code == "invalid_path"
    assert captured.value.requested_path == requested_path


def test_resolve_rejects_parent_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    policy = WorkspacePathPolicy(workspace)

    with pytest.raises(PathPolicyError) as captured:
        policy.resolve("../secret.txt")

    assert captured.value.code == "outside_workspace"


def test_resolve_rejects_a_sibling_with_the_same_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    sibling = tmp_path / "work-backup"
    sibling.mkdir()
    target = sibling / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    policy = WorkspacePathPolicy(workspace)

    with pytest.raises(PathPolicyError) as captured:
        policy.resolve(str(target))

    assert captured.value.code == "outside_workspace"


def test_resolve_reports_a_missing_read_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = WorkspacePathPolicy(workspace)

    with pytest.raises(PathPolicyError) as captured:
        policy.resolve("missing.txt")

    assert captured.value.code == "not_found"


def test_resolve_classifies_a_non_missing_resolution_error_as_invalid_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = WorkspacePathPolicy(workspace)

    def fail_to_resolve(_path: Path, *, strict: bool = False) -> Path:
        del strict
        raise OSError("simulated permission or filesystem failure")

    monkeypatch.setattr(Path, "resolve", fail_to_resolve)

    with pytest.raises(PathPolicyError) as captured:
        policy.resolve("unreadable.txt")

    assert captured.value.code == "invalid_path"


def test_resolve_allows_a_missing_write_target_inside_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "notes"
    nested.mkdir()
    policy = WorkspacePathPolicy(workspace)

    resolved = policy.resolve("notes/../result.txt", must_exist=False)

    assert resolved == workspace / "result.txt"


def test_resolve_rejects_a_symlink_that_escapes_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    link = workspace / "linked-outside"
    _create_directory_link(outside, link)
    policy = WorkspacePathPolicy(workspace)

    with pytest.raises(PathPolicyError) as captured:
        policy.resolve("linked-outside/secret.txt")

    assert captured.value.code == "outside_workspace"
