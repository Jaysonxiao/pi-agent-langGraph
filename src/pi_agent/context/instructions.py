"""Discover and load workspace instruction files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pi_agent.security import PathPolicyError, WorkspacePathPolicy

INSTRUCTION_FILENAME = "AGENTS.md"
PI_INSTRUCTION_FILENAME = "PI-AGENTS.md"
InstructionLoadCode = Literal[
    "not_found", "not_file", "read_error", "invalid_utf8", "outside_workspace"
]


@dataclass(frozen=True, slots=True)
class WorkspaceInstruction:
    """One decoded workspace instruction and its canonical source path."""

    path: Path
    content: str
    utf8_bytes: int


class InstructionLoadError(ValueError):
    """A stable, source-specific failure while reading an instruction file."""

    def __init__(self, code: InstructionLoadCode, path: Path, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


def discover_workspace_instruction_files(
    policy: WorkspacePathPolicy,
    active_path: str,
    instruction_filename: str = INSTRUCTION_FILENAME,
) -> tuple[Path, ...]:
    """Return matching ancestor instruction files from workspace root to active directory."""
    if not instruction_filename or Path(instruction_filename).name != instruction_filename:
        raise ValueError("instruction_filename must be a single file name.")
    active = policy.resolve(active_path)
    # 文件从父目录起算; 目录把自己算进祖先链.
    active_directory = active.parent if active.is_file() else active
    return tuple(
        instruction
        for directory in _ancestor_directories(policy.root, active_directory)
        if (instruction := _instruction_file(policy, directory, instruction_filename)) is not None
    )


def load_workspace_instructions(
    policy: WorkspacePathPolicy,
    paths: tuple[Path, ...],
) -> tuple[WorkspaceInstruction, ...]:
    """Read discovered instruction paths in precedence order."""
    # 只读调用方给出的路径, 保持宽到窄顺序, 不再扫描仓库.
    return tuple(_load_instruction(policy, path) for path in paths)


def _load_instruction(policy: WorkspacePathPolicy, path: Path) -> WorkspaceInstruction:
    try:
        canonical = policy.resolve(str(path))
    except PathPolicyError as error:
        raise InstructionLoadError(_load_code_from_policy(error.code), path, str(error)) from error

    # 发现阶段可能漏过同名目录; 读取阶段仍拒绝, 避免把目录当规则原文.
    if not canonical.is_file():
        raise InstructionLoadError(
            "not_file",
            canonical,
            f"Instruction path is not a file: {canonical}",
        )

    try:
        raw = canonical.read_bytes()
    except OSError as error:
        raise InstructionLoadError(
            "read_error",
            canonical,
            f"Failed to read instruction file: {canonical}",
        ) from error

    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InstructionLoadError(
            "invalid_utf8",
            canonical,
            f"Instruction file is not valid UTF-8: {canonical}",
        ) from error

    # content 统一成逻辑换行便于装配 prompt; 字节数必须反映磁盘原文, 不受规范化影响.
    return WorkspaceInstruction(
        path=canonical,
        content=decoded.replace("\r\n", "\n").replace("\r", "\n"),
        utf8_bytes=len(raw),
    )


def _load_code_from_policy(code: str) -> InstructionLoadCode:
    if code == "outside_workspace":
        return "outside_workspace"
    if code == "not_found":
        return "not_found"
    return "read_error"


def _ancestor_directories(root: Path, active_directory: Path) -> tuple[Path, ...]:
    # 只拼 root -> leaf, 不 glob 兄弟目录.
    directories = [root]
    current = root
    for part in active_directory.relative_to(root).parts:
        current = current / part
        directories.append(current)
    return tuple(directories)


def _instruction_file(
    policy: WorkspacePathPolicy,
    directory: Path,
    instruction_filename: str = INSTRUCTION_FILENAME,
) -> Path | None:
    try:
        candidate = policy.resolve(str(directory / instruction_filename))
    except PathPolicyError as error:
        if error.code == "not_found":
            return None
        raise
    # 同名目录不是指令文件, 不能混进 prompt 发现结果.
    return candidate if candidate.is_file() else None
