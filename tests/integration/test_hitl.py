"""End-to-end evidence for the M4 prepare -> approval -> apply boundary."""

from pathlib import Path
from typing import cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, Interrupt

from pi_agent.domain.approval import FileApprovalState, create_file_approval_state
from pi_agent.graph.file_approval import build_file_approval_graph
from pi_agent.security import WorkspacePathPolicy
from pi_agent.tools.file_apply import apply_approved_file_change
from pi_agent.tools.file_mutation import (
    EditArguments,
    FileChangePlanner,
    FileMutationError,
    to_pending_file_change,
)


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _interrupt_from(result: object) -> Interrupt:
    output = cast(dict[str, object], result)
    interrupts = cast(tuple[Interrupt, ...], output["__interrupt__"])
    assert len(interrupts) == 1
    return interrupts[0]


def _prepared_state(policy: WorkspacePathPolicy) -> FileApprovalState:
    prepared = FileChangePlanner(policy).prepare_edit(
        EditArguments(
            path="README.md",
            old_text="M1 establishes the package.",
            new_text="M1-M4 establish the core loop.",
        )
    )
    return create_file_approval_state(
        to_pending_file_change(
            prepared,
            preview="- M1 establishes the package.\n+ + M1-M4 establish the core loop.",
        )
    )


def test_prepare_approval_apply_is_safe_and_resumable(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    original = "M1 establishes the package.\r\n"
    replacement = "M1-M4 establish the core loop.\r\n"
    target.write_text(original, encoding="utf-8", newline="")
    policy = WorkspacePathPolicy(tmp_path)
    state = _prepared_state(policy)
    graph = build_file_approval_graph()
    config = _config("integration-approve")

    paused = graph.invoke(state, config=config)
    assert _interrupt_from(paused).value["kind"] == "file_change_approval"
    with target.open("r", encoding="utf-8", newline="") as stream:
        assert stream.read() == original

    approved = cast(
        FileApprovalState,
        graph.invoke(Command(resume={"decision": "approve"}), config=config),
    )
    result = apply_approved_file_change(approved, policy)

    with target.open("r", encoding="utf-8", newline="") as stream:
        assert stream.read() == replacement
    assert result.path == str(target.resolve())


def test_rejected_approval_cannot_apply(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    original = "M1 establishes the package.\n"
    target.write_text(original, encoding="utf-8", newline="")
    policy = WorkspacePathPolicy(tmp_path)
    state = _prepared_state(policy)
    graph = build_file_approval_graph()
    config = _config("integration-reject")
    graph.invoke(state, config=config)

    rejected = cast(
        FileApprovalState,
        graph.invoke(
            Command(resume={"decision": "reject", "reason": "Review later"}),
            config=config,
        ),
    )

    with pytest.raises(FileMutationError, match="approved"):
        apply_approved_file_change(rejected, policy)
    assert target.read_text(encoding="utf-8") == original


def test_approved_proposal_refuses_stale_disk_version(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("M1 establishes the package.\n", encoding="utf-8", newline="")
    policy = WorkspacePathPolicy(tmp_path)
    state = _prepared_state(policy)
    graph = build_file_approval_graph()
    config = _config("integration-stale")
    graph.invoke(state, config=config)
    approved = cast(
        FileApprovalState,
        graph.invoke(Command(resume={"decision": "approve"}), config=config),
    )
    target.write_text("changed by another process\n", encoding="utf-8", newline="")

    with pytest.raises(FileMutationError, match="version"):
        apply_approved_file_change(approved, policy)
    assert target.read_text(encoding="utf-8") == "changed by another process\n"
