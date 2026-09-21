"""Side-effect-free preparation for workspace file mutations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pi_agent.domain.approval import PendingFileChange
from pi_agent.security import WorkspacePathPolicy

FileMutationCode = Literal[
    "empty_old_text",
    "match_not_found",
    "match_not_unique",
    "no_change",
    "invalid_target",
    "not_utf8",
    "read_failed",
    "version_changed",
    "write_failed",
]
FileMutationOperation = Literal["write", "edit"]


class FileMutationError(ValueError):
    """Stable failure raised before approval or filesystem mutation."""

    def __init__(self, code: FileMutationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class WriteArguments(BaseModel):
    """Model-visible arguments for a complete UTF-8 file replacement."""

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str


class EditArguments(BaseModel):
    """Model-visible arguments for one exact text replacement."""

    model_config = ConfigDict(extra="forbid")

    path: str
    old_text: str
    new_text: str


@dataclass(frozen=True, slots=True)
class PreparedFileChange:
    """A deterministic proposal that has not performed a write."""

    operation: FileMutationOperation
    requested_path: str
    target: Path
    before_text: str | None
    after_text: str
    before_sha256: str | None


@dataclass(frozen=True, slots=True)
class FileChangePlanner:
    """Authorize paths and derive file content without mutating the workspace."""

    paths: WorkspacePathPolicy

    def prepare_write(self, args: WriteArguments) -> PreparedFileChange:
        """Prepare a complete replacement while leaving the target untouched."""
        target = self.paths.resolve(args.path, must_exist=False)
        before_text: str | None = None
        if target.exists():
            _require_file(target)
            before_text = _read_utf8_exact(target)
        return PreparedFileChange(
            operation="write",
            requested_path=args.path,
            target=target,
            before_text=before_text,
            after_text=args.content,
            before_sha256=_sha256(before_text) if before_text is not None else None,
        )

    def prepare_edit(self, args: EditArguments) -> PreparedFileChange:
        """Prepare one exact replacement while leaving the target untouched."""
        target = self.paths.resolve(args.path)
        _require_file(target)
        before_text = _read_utf8_exact(target)
        after_text = apply_exact_replacement(before_text, args.old_text, args.new_text)
        return PreparedFileChange(
            operation="edit",
            requested_path=args.path,
            target=target,
            before_text=before_text,
            after_text=after_text,
            before_sha256=_sha256(before_text),
        )


def to_pending_file_change(prepared: PreparedFileChange, *, preview: str) -> PendingFileChange:
    """Serialize a prepared proposal for checkpoint and approval state."""

    return {
        "operation": prepared.operation,
        "path": str(prepared.target),
        "before_sha256": prepared.before_sha256,
        "after_sha256": _sha256(prepared.after_text),
        "after_text": prepared.after_text,
        "preview": preview,
    }


def apply_exact_replacement(original: str, old_text: str, new_text: str) -> str:
    """Return one uniquely targeted replacement without touching the filesystem."""
    if old_text == "":
        raise FileMutationError("empty_old_text", "Exact replacement target must not be empty.")

    if old_text == new_text:
        raise FileMutationError("no_change", "Exact replacement must change the file content.")

    match_offset = original.find(old_text)
    if match_offset == -1:
        raise FileMutationError("match_not_found", "Exact replacement target was not found.")

    next_match_offset = original.find(old_text, match_offset + 1)
    if next_match_offset != -1:
        raise FileMutationError("match_not_unique", "Exact replacement target must be unique.")

    after_text = original[:match_offset] + new_text + original[match_offset + len(old_text) :]

    return after_text


def _require_file(target: Path) -> None:
    if not target.is_file():
        raise FileMutationError("invalid_target", "Mutation target must identify a file.")


def _read_utf8_exact(target: Path) -> str:
    """Read UTF-8 while preserving BOM characters and exact newline sequences."""
    try:
        with target.open("r", encoding="utf-8", newline="") as stream:
            return stream.read()
    except UnicodeDecodeError as exc:
        raise FileMutationError("not_utf8", "Mutation target must be UTF-8 text.") from exc
    except OSError as exc:
        raise FileMutationError("read_failed", "Mutation target could not be read.") from exc


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
