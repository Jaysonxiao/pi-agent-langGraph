"""Acceptance tests for approved, version-checked atomic file application."""

import hashlib
from pathlib import Path

import pytest

from pi_agent.domain.approval import (
    FileApprovalState,
    PendingFileChange,
    create_file_approval_state,
)
from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.file_apply import apply_approved_file_change
from pi_agent.tools.file_mutation import FileMutationError


def _state(path: str, *, before_sha256: str | None, after_text: str) -> FileApprovalState:
    change: PendingFileChange = {
        "operation": "edit",
        "path": path,
        "before_sha256": before_sha256,
        "after_sha256": "after-hash",
        "after_text": after_text,
        "preview": after_text,
    }
    state = create_file_approval_state(change)
    state["approval_status"] = "approved"
    return state


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_unapproved_state_is_rejected_without_touching_file(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("original", encoding="utf-8", newline="")
    state = create_file_approval_state(
        {
            "operation": "edit",
            "path": "README.md",
            "before_sha256": "before-hash",
            "after_sha256": "after-hash",
            "after_text": "replacement",
            "preview": "replacement",
        }
    )

    with pytest.raises(FileMutationError, match="approved"):
        apply_approved_file_change(state, WorkspacePathPolicy(tmp_path))

    assert target.read_text(encoding="utf-8") == "original"


def test_state_builder_preserves_serialized_proposal() -> None:
    state = _state("README.md", before_sha256="before-hash", after_text="replacement")

    assert state["pending_change"]["after_text"] == "replacement"
    assert state["approval_status"] == "approved"


def test_changed_disk_version_is_rejected_before_write(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("changed on disk", encoding="utf-8", newline="")
    state = _state("README.md", before_sha256="stale-hash", after_text="replacement")

    with pytest.raises(FileMutationError, match="version"):
        apply_approved_file_change(state, WorkspacePathPolicy(tmp_path))

    assert target.read_text(encoding="utf-8") == "changed on disk"


def test_approved_edit_replaces_content_atomically(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("old\r\nline", encoding="utf-8", newline="")
    state = _state(
        "README.md",
        before_sha256=_sha256("old\r\nline"),
        after_text="new\r\nline",
    )
    state["pending_change"]["after_sha256"] = _sha256("new\r\nline")

    result = apply_approved_file_change(state, WorkspacePathPolicy(tmp_path))

    assert result.path == str(target.resolve())
    with target.open("r", encoding="utf-8", newline="") as stream:
        assert stream.read() == "new\r\nline"
    assert result.after_sha256 == _sha256("new\r\nline")


def test_approved_write_can_create_new_file_atomically(tmp_path: Path) -> None:
    change: PendingFileChange = {
        "operation": "write",
        "path": "new.txt",
        "before_sha256": None,
        "after_sha256": _sha256("new content"),
        "after_text": "new content",
        "preview": "new content",
    }
    state = create_file_approval_state(change)
    state["approval_status"] = "approved"

    result = apply_approved_file_change(state, WorkspacePathPolicy(tmp_path))

    assert Path(result.path).read_text(encoding="utf-8") == "new content"
