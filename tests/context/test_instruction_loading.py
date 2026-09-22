"""Red tests for M7.2 workspace instruction loading."""

from pathlib import Path

import pytest

from pi_agent.context import (
    InstructionLoadError,
    WorkspaceInstruction,
    load_workspace_instructions,
)
from pi_agent.security import WorkspacePathPolicy


def _policy(tmp_path: Path) -> WorkspacePathPolicy:
    return WorkspacePathPolicy(tmp_path)


def test_loads_utf8_content_in_given_precedence_order(tmp_path: Path) -> None:
    root = tmp_path / "AGENTS.md"
    leaf = tmp_path / "packages" / "AGENTS.md"
    leaf.parent.mkdir()
    root.write_text("根规则\n", encoding="utf-8", newline="\n")
    leaf.write_text("leaf rule\n", encoding="utf-8", newline="\n")

    result = load_workspace_instructions(
        _policy(tmp_path),
        (root.resolve(), leaf.resolve()),
    )

    assert result == (
        WorkspaceInstruction(root.resolve(), "根规则\n", len("根规则\n".encode())),
        WorkspaceInstruction(leaf.resolve(), "leaf rule\n", len(b"leaf rule\n")),
    )


def test_rejects_path_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-AGENTS.md"
    outside.write_text("no", encoding="utf-8")

    with pytest.raises(InstructionLoadError) as exc_info:
        load_workspace_instructions(_policy(tmp_path), (outside.resolve(),))

    assert exc_info.value.code == "outside_workspace"


def test_reports_invalid_utf8_with_source_path(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_bytes(b"valid\xff")

    with pytest.raises(InstructionLoadError) as exc_info:
        load_workspace_instructions(_policy(tmp_path), (path.resolve(),))

    assert exc_info.value.code == "invalid_utf8"
    assert exc_info.value.path == path.resolve()


def test_reports_missing_or_directory_sources(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    directory = tmp_path / "AGENTS.md"
    directory.mkdir()

    with pytest.raises(InstructionLoadError) as missing_info:
        load_workspace_instructions(_policy(tmp_path), (missing,))
    assert missing_info.value.code == "not_found"

    with pytest.raises(InstructionLoadError) as directory_info:
        load_workspace_instructions(_policy(tmp_path), (directory,))
    assert directory_info.value.code == "not_file"


def test_counts_bytes_from_original_utf8_file_not_normalized_text(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    raw = b"root\r\nrule\r\n"
    path.write_bytes(raw)

    result = load_workspace_instructions(_policy(tmp_path), (path,))

    assert result[0].utf8_bytes == len(raw)
