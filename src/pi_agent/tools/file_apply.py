"""已批准文件变更的落盘边界 (M4).

审批只证明用户同意了 checkpoint 里的提案, 不证明磁盘仍是同一版本.
本模块在写入前重新授权路径并核对 SHA-256; 真正副作用只发生在
同目录临时文件 + ``os.replace`` 这一步.
"""

import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pi_agent.domain.approval import FileApprovalState
from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.file_mutation import (
    FileMutationError,
    _read_utf8_exact,
    _require_file,
    _sha256,
)


@dataclass(frozen=True, slots=True)
class AppliedFileChange:
    """落盘成功后的稳定结果, 不回传完整文件内容."""

    path: str
    before_sha256: str | None
    after_sha256: str


def apply_approved_file_change(
    state: FileApprovalState, paths: WorkspacePathPolicy
) -> AppliedFileChange:
    """复核提案并把 ``after_text`` 原子写入工作区."""

    # 未批准不得读/写目标, 避免把拒绝或仍待审的提案落到磁盘.
    if state["approval_status"] != "approved":
        raise FileMutationError(
            "write_failed",
            "File change must be approved before it is applied.",
        )

    change = state["pending_change"]
    # edit 要求目标已存在; write 允许创建新文件, 但仍须通过 workspace 门禁.
    must_exist = change["operation"] == "edit"
    target = paths.resolve(change["path"], must_exist=must_exist)

    before_text: str | None = None
    if target.exists():
        _require_file(target)
        before_text = _read_utf8_exact(target)

    # 批准后若其他进程改过文件, 旧提案不得覆盖新内容.
    actual_before = _sha256(before_text) if before_text is not None else None
    if actual_before != change["before_sha256"]:
        raise FileMutationError(
            "version_changed",
            "Workspace file version changed after approval.",
        )

    tmp_path: Path | None = None
    previous_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    replaced = False
    try:
        try:
            # 同目录临时文件才能让 os.replace 在同一文件系统上原子替换.
            fd, tmp_name = tempfile.mkstemp(dir=target.parent)
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(change["after_text"])
                stream.flush()
                os.fsync(stream.fileno())  # 先刷到磁盘, 再替换可见目标.
            if previous_mode is not None:
                os.chmod(tmp_path, previous_mode)
            os.replace(tmp_path, target)
            replaced = True
        except OSError as exc:
            raise FileMutationError(
                "write_failed",
                "Approved file change could not be written.",
            ) from exc
    finally:
        # replace 成功后临时路径已不存在; 失败时必须清掉半写入残留.
        if tmp_path is not None and not replaced:
            tmp_path.unlink(missing_ok=True)

    return AppliedFileChange(
        path=str(target),
        before_sha256=actual_before,
        # 以实际写入的 after_text 计算哈希, 不盲信提案里的 after_sha256.
        after_sha256=_sha256(change["after_text"]),
    )
