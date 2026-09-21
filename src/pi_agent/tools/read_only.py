"""Workspace-confined read, list, and literal text-search tools."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pi_agent.security import PathPolicyError, WorkspacePathPolicy
from pi_agent.tools.base import ToolDefinition
from pi_agent.tools.output import TextOutputBudget


class ReadArguments(BaseModel):
    """Model-visible arguments for reading one UTF-8 text window."""

    model_config = ConfigDict(extra="forbid")

    path: str
    offset: int = Field(default=1, ge=1)
    limit: int | None = Field(default=None, ge=1)


class ListArguments(BaseModel):
    """Model-visible arguments for listing direct directory children."""

    model_config = ConfigDict(extra="forbid")

    path: str = "."


class SearchArguments(BaseModel):
    """Model-visible arguments for bounded recursive literal search."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    path: str = "."
    case_sensitive: bool = True


@dataclass(frozen=True, slots=True)
class ReadTextHandler:
    """Read a caller-selected line window after path authorization."""

    paths: WorkspacePathPolicy
    output: TextOutputBudget

    def __call__(self, args: ReadArguments) -> str:
        """Return one bounded UTF-8 text window."""
        target = self.paths.resolve(args.path)
        if not target.is_file():
            raise ValueError("Read path must identify a file.")

        text = _read_utf8(target)
        lines = text.splitlines()
        if args.offset > max(1, len(lines)):
            raise ValueError(
                f"Offset {args.offset} is beyond end of file ({len(lines)} lines total)."
            )

        start = args.offset - 1
        end = None if args.limit is None else start + args.limit
        selected = "\n".join(lines[start:end])
        return self.output.apply(selected).render()


@dataclass(frozen=True, slots=True)
class ListDirectoryHandler:
    """List direct children in deterministic name order."""

    paths: WorkspacePathPolicy
    output: TextOutputBudget

    def __call__(self, args: ListArguments) -> str:
        """Return a bounded, stable directory listing."""
        target = self.paths.resolve(args.path)
        if not target.is_dir():
            raise ValueError("List path must identify a directory.")

        try:
            entries = sorted(
                target.iterdir(), key=lambda entry: (entry.name.casefold(), entry.name)
            )
        except OSError as exc:
            raise RuntimeError("Directory could not be listed.") from exc

        lines = [f"{_entry_kind(entry)}\t{entry.name}" for entry in entries]
        return self.output.apply("\n".join(lines)).render()


@dataclass(frozen=True, slots=True)
class SearchTextHandler:
    """Search UTF-8 files without following paths outside the workspace."""

    paths: WorkspacePathPolicy
    output: TextOutputBudget
    max_files: int = 1_000
    max_matches: int = 200

    def __post_init__(self) -> None:
        """Bound search work independently from returned output size."""
        if self.max_files <= 0:
            raise ValueError("max_files must be greater than zero.")
        if self.max_matches <= 0:
            raise ValueError("max_matches must be greater than zero.")

    def __call__(self, args: SearchArguments) -> str:
        """Return bounded workspace-relative literal matches."""
        root = self.paths.resolve(args.path)
        if not root.is_file() and not root.is_dir():
            raise ValueError("Search path must identify a file or directory.")

        query = args.query if args.case_sensitive else args.query.casefold()
        matches: list[str] = []
        scanned_files = 0
        skipped_files = 0
        stopped_by: str | None = None

        for candidate in self._iter_files(root):
            if scanned_files >= self.max_files:
                stopped_by = f"file limit ({self.max_files})"
                break
            scanned_files += 1
            try:
                text = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                skipped_files += 1
                continue

            for line_number, line in enumerate(text.splitlines(), start=1):
                searchable = line if args.case_sensitive else line.casefold()
                if query not in searchable:
                    continue
                relative = candidate.relative_to(self.paths.root).as_posix()
                matches.append(f"{relative}:{line_number}:{line}")
                if len(matches) >= self.max_matches:
                    stopped_by = f"match limit ({self.max_matches})"
                    break
            if stopped_by is not None:
                break

        lines = matches or ["No matches."]
        if skipped_files:
            lines.append(f"[Skipped {skipped_files} unreadable or non-UTF-8 files.]")
        if stopped_by is not None:
            lines.append(f"[Search stopped at {stopped_by}.]")
        return self.output.apply("\n".join(lines)).render()

    def _iter_files(self, root: Path) -> list[Path]:
        """Collect a deterministic bounded-candidate order without escaping root."""
        if root.is_file():
            return [root]

        files: list[Path] = []
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            allowed_directories: list[str] = []
            for name in sorted(directory_names, key=lambda value: (value.casefold(), value)):
                try:
                    self.paths.resolve(str(directory_path / name))
                except PathPolicyError:
                    continue
                allowed_directories.append(name)
            directory_names[:] = allowed_directories

            for name in sorted(file_names, key=lambda value: (value.casefold(), value)):
                try:
                    candidate = self.paths.resolve(str(directory_path / name))
                except PathPolicyError:
                    continue
                if candidate.is_file():
                    files.append(candidate)
                if len(files) > self.max_files:
                    return files
        return files


def create_read_tool(
    paths: WorkspacePathPolicy,
    output: TextOutputBudget | None = None,
) -> ToolDefinition[ReadArguments]:
    """Create the UTF-8 read tool from explicit runtime capabilities."""
    budget = output or TextOutputBudget()
    return ToolDefinition(
        name="read",
        description=(
            "Read a UTF-8 text file inside the workspace using 1-indexed offset and limit. "
            f"Output is limited to {budget.max_lines} lines and {budget.max_bytes} UTF-8 bytes."
        ),
        args_schema=ReadArguments,
        handler=ReadTextHandler(paths, budget),
    )


def create_list_tool(
    paths: WorkspacePathPolicy,
    output: TextOutputBudget | None = None,
) -> ToolDefinition[ListArguments]:
    """Create the deterministic direct-directory listing tool."""
    budget = output or TextOutputBudget()
    return ToolDefinition(
        name="list",
        description=(
            "List direct children of a workspace directory in stable order. "
            f"Output is limited to {budget.max_lines} lines and {budget.max_bytes} UTF-8 bytes."
        ),
        args_schema=ListArguments,
        handler=ListDirectoryHandler(paths, budget),
    )


def create_search_tool(
    paths: WorkspacePathPolicy,
    output: TextOutputBudget | None = None,
    *,
    max_files: int = 1_000,
    max_matches: int = 200,
) -> ToolDefinition[SearchArguments]:
    """Create a bounded recursive literal-text search tool."""
    budget = output or TextOutputBudget()
    return ToolDefinition(
        name="search",
        description=(
            "Search UTF-8 files under a workspace path for a literal string. "
            f"Scans at most {max_files} files and returns at most {max_matches} matches."
        ),
        args_schema=SearchArguments,
        handler=SearchTextHandler(paths, budget, max_files=max_files, max_matches=max_matches),
    )


def _read_utf8(path: Path) -> str:
    """Normalize host read/decode failures at the tool boundary."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Read only supports UTF-8 text files in M4.") from exc
    except OSError as exc:
        raise RuntimeError("File could not be read.") from exc


def _entry_kind(path: Path) -> str:
    """Describe an entry from lstat metadata without following a reparse target."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError("Directory entry metadata could not be read.") from exc

    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(metadata.st_mode) or (reparse_point and file_attributes & reparse_point):
        return "link"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return "other"
