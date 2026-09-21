"""Acceptance tests for the M4 human-approval boundary."""

import json
from typing import cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, Interrupt
from pydantic import ValidationError

from pi_agent.domain.approval import (
    FileApprovalState,
    PendingFileChange,
    create_file_approval_state,
)
from pi_agent.graph.file_approval import (
    build_file_approval_graph,
    build_file_approval_request,
)


def _change() -> PendingFileChange:
    return {
        "operation": "edit",
        "path": "README.md",
        "before_sha256": "before-hash",
        "after_sha256": "after-hash",
        "after_text": "full replacement text that must remain internal",
        "preview": "- old line\n+ new line",
    }


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _interrupt_from(result: object) -> Interrupt:
    output = cast(dict[str, object], result)
    interrupts = cast(tuple[Interrupt, ...], output["__interrupt__"])
    assert len(interrupts) == 1
    return interrupts[0]


def test_initial_approval_state_is_pending_and_json_serializable() -> None:
    state = create_file_approval_state(_change())

    assert state["approval_status"] == "pending"
    assert state["rejection_reason"] is None
    assert json.loads(json.dumps(state)) == state


def test_approval_request_is_bounded_and_excludes_full_after_text() -> None:
    request = build_file_approval_request(_change())

    assert request == {
        "kind": "file_change_approval",
        "question": "Approve this workspace file change?",
        "change": {
            "operation": "edit",
            "path": "README.md",
            "before_sha256": "before-hash",
            "after_sha256": "after-hash",
            "preview": "- old line\n+ new line",
        },
    }
    assert "full replacement text" not in json.dumps(request)


def test_graph_pauses_before_any_file_change() -> None:
    graph = build_file_approval_graph()
    config = _config("pause-case")
    initial = create_file_approval_state(_change())

    result = graph.invoke(initial, config=config)
    interruption = _interrupt_from(result)

    assert interruption.value == build_file_approval_request(_change())
    snapshot = cast(FileApprovalState, graph.get_state(config).values)
    assert snapshot["approval_status"] == "pending"
    assert snapshot["pending_change"]["after_text"] == _change()["after_text"]


def test_same_thread_can_resume_with_approval() -> None:
    graph = build_file_approval_graph()
    config = _config("approve-case")
    initial = create_file_approval_state(_change())
    graph.invoke(initial, config=config)

    result = cast(
        FileApprovalState,
        graph.invoke(Command(resume={"decision": "approve"}), config=config),
    )

    assert result["approval_status"] == "approved"
    assert result["rejection_reason"] is None
    assert result["pending_change"] == initial["pending_change"]


def test_same_thread_can_resume_with_rejection_reason() -> None:
    graph = build_file_approval_graph()
    config = _config("reject-case")
    initial = create_file_approval_state(_change())
    graph.invoke(initial, config=config)

    result = cast(
        FileApprovalState,
        graph.invoke(
            Command(resume={"decision": "reject", "reason": "Wrong target file"}),
            config=config,
        ),
    )

    assert result["approval_status"] == "rejected"
    assert result["rejection_reason"] == "Wrong target file"
    assert result["pending_change"] == initial["pending_change"]


def test_non_pending_state_is_rejected_before_interrupt() -> None:
    graph = build_file_approval_graph()
    initial = create_file_approval_state(_change())
    initial["approval_status"] = "approved"

    with pytest.raises(ValueError, match="pending"):
        graph.invoke(initial, config=_config("already-approved-case"))


def test_resume_payload_rejects_unexpected_fields() -> None:
    graph = build_file_approval_graph()
    config = _config("invalid-resume-case")
    graph.invoke(create_file_approval_state(_change()), config=config)

    with pytest.raises(ValidationError):
        graph.invoke(
            Command(resume={"decision": "approve", "unexpected": True}),
            config=config,
        )
