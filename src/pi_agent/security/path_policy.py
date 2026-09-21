"""Workspace path confinement shared by all file-mutating capabilities."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PathPolicyCode = Literal["invalid_path", "not_found", "outside_workspace"]


class PathPolicyError(ValueError):
    """A stable policy failure that tools may safely expose to the model."""

    def __init__(self, code: PathPolicyCode, requested_path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.requested_path = requested_path


@dataclass(frozen=True, slots=True)
class WorkspacePathPolicy:
    """Resolve model-supplied paths without permitting workspace escape."""

    root: Path

    def __post_init__(self) -> None:
        """Store one existing, canonical workspace root."""
        try:
            canonical_root = self.root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Workspace root does not exist: {self.root}") from exc
        if not canonical_root.is_dir():
            raise ValueError(f"Workspace root is not a directory: {self.root}")
        object.__setattr__(self, "root", canonical_root)

    def resolve(self, requested_path: str, *, must_exist: bool = True) -> Path:
        """Return a canonical path inside ``root`` or raise ``PathPolicyError``."""
        if "\x00" in requested_path or requested_path.strip() == "":
            raise PathPolicyError(
                "invalid_path",
                requested_path,
                "Path is empty, whitespace-only, or contains a NUL byte.",
            )

        raw = Path(requested_path)
        candidate = raw if raw.is_absolute() else self.root / raw
        try:
            resolved = candidate.resolve(strict=False)
        except FileNotFoundError as exc:
            raise PathPolicyError(
                "not_found",
                requested_path,
                "Path does not exist.",
            ) from exc
        except (OSError, RuntimeError) as exc:
            raise PathPolicyError(
                "invalid_path",
                requested_path,
                "Path could not be resolved.",
            ) from exc

        if not resolved.is_relative_to(self.root):
            raise PathPolicyError(
                "outside_workspace",
                requested_path,
                "Resolved path is outside the workspace root.",
            )

        if must_exist and not resolved.exists():
            raise PathPolicyError(
                "not_found",
                requested_path,
                "Path does not exist.",
            )

        return resolved
