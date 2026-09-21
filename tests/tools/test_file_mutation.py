"""M4 contracts for side-effect-free file-change preparation."""

import hashlib
from pathlib import Path

import pytest

from pi_agent.security import PathPolicyError, WorkspacePathPolicy
from pi_agent.tools.file_mutation import (
    EditArguments,
    FileChangePlanner,
    FileMutationError,
    WriteArguments,
    apply_exact_replacement,
)


def test_prepare_write_for_a_new_file_has_no_side_effect(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    planner = FileChangePlanner(WorkspacePathPolicy(workspace))

    change = planner.prepare_write(WriteArguments(path="notes/new.txt", content="draft"))

    assert change.operation == "write"
    assert change.target == workspace / "notes" / "new.txt"
    assert change.before_text is None
    assert change.before_sha256 is None
    assert change.after_text == "draft"
    assert not change.target.exists()
    assert not change.target.parent.exists()


def test_prepare_write_records_the_exact_existing_version(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_bytes(b"one\r\ntwo")
    planner = FileChangePlanner(WorkspacePathPolicy(workspace))

    change = planner.prepare_write(WriteArguments(path="notes.txt", content="replacement"))

    assert change.before_text == "one\r\ntwo"
    assert change.before_sha256 == hashlib.sha256(b"one\r\ntwo").hexdigest()
    assert target.read_bytes() == b"one\r\ntwo"


def test_prepare_edit_builds_a_unique_change_without_writing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "README.md"
    target.write_bytes(b"M1 establishes the package.\nNext step.")
    planner = FileChangePlanner(WorkspacePathPolicy(workspace))

    change = planner.prepare_edit(
        EditArguments(
            path="README.md",
            old_text="M1 establishes the package.",
            new_text="M1-M4 establish the core loop.",
        )
    )

    assert change.operation == "edit"
    assert change.after_text == "M1-M4 establish the core loop.\nNext step."
    assert target.read_text(encoding="utf-8") == "M1 establishes the package.\nNext step."


@pytest.mark.parametrize(
    ("original", "old_text", "expected_code"),
    [
        ("alpha", "", "empty_old_text"),
        ("alpha", "missing", "match_not_found"),
        ("alpha alpha", "alpha", "match_not_unique"),
        ("aaa", "aa", "match_not_unique"),
    ],
)
def test_exact_replacement_rejects_an_unsafe_match_contract(
    original: str,
    old_text: str,
    expected_code: str,
) -> None:
    with pytest.raises(FileMutationError) as captured:
        apply_exact_replacement(original, old_text, "updated")

    assert captured.value.code == expected_code


def test_exact_replacement_rejects_a_no_op() -> None:
    with pytest.raises(FileMutationError) as captured:
        apply_exact_replacement("alpha", "alpha", "alpha")

    assert captured.value.code == "no_change"


def test_exact_replacement_preserves_bom_and_crlf() -> None:
    original = "\ufeffheading\r\nold value\r\ntail"

    result = apply_exact_replacement(original, "old value", "new value")

    assert result == "\ufeffheading\r\nnew value\r\ntail"


def test_prepare_edit_rejects_escape_before_reading_the_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read", encoding="utf-8")
    planner = FileChangePlanner(WorkspacePathPolicy(workspace))

    with pytest.raises(PathPolicyError) as captured:
        planner.prepare_edit(EditArguments(path="../secret.txt", old_text="do", new_text="x"))

    assert captured.value.code == "outside_workspace"
    assert outside.read_text(encoding="utf-8") == "do not read"
