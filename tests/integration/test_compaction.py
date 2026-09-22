"""Actual graph/checkpoint acceptance for summary success, failure and recovery."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from pi_agent.context import ContextConfig, ModelSummarizer
from pi_agent.domain.state import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph, build_tool_graph
from pi_agent.models.fake import FakeChatModel, ScriptedChatModel
from pi_agent.security import WorkspacePathPolicy
from pi_agent.sessions import open_sqlite_checkpointer, run_session_turn, session_config
from pi_agent.tools import RecordingAddHandler, ToolRegistry, create_add_tool


@pytest.mark.parametrize(
    "failure",
    ["success", "summary_error", "blank", "over_budget", "invalid_utf8", "missing", "outside"],
)
def test_sqlite_original_history_survives_context_failure_and_reopen(
    tmp_path: Path,
    failure: str,
) -> None:
    database = tmp_path / "state.sqlite"
    config = session_config("session")
    with open_sqlite_checkpointer(database) as saver:
        graph = build_minimal_graph(saver)
        first = run_session_turn(
            graph,
            session_id="session",
            content="old " * 100,
            message_id="u1",
            context=RunContext(model=FakeChatModel("remembered")),
        )
        previous = graph.get_state(config)
        previous_messages = list(first["messages"])
        model = ScriptedChatModel([AIMessage("final", id="a2")])
        summary_model = FakeChatModel(
            " " if failure == "blank" else "short",
            error=RuntimeError("provider detail") if failure == "summary_error" else None,
        )
        context_config = ContextConfig(
            max_bytes=1 if failure == "over_budget" else 100,
            summarizer=ModelSummarizer(summary_model),
        )
        if failure in ("invalid_utf8", "missing", "outside"):
            (tmp_path / "AGENTS.md").write_bytes(b"\xff" if failure == "invalid_utf8" else b"ok")
            active = "missing.py" if failure == "missing" else ".." if failure == "outside" else "."
            context_config = ContextConfig(
                workspace_policy=WorkspacePathPolicy(tmp_path), active_path=active
            )
        result = run_session_turn(
            graph,
            session_id="session",
            content="new",
            message_id="u2",
            context=RunContext(model=model, context_config=context_config),
        )
        # The original checkpoint remains addressable and unchanged.
        assert graph.get_state(previous.config).values["messages"] == previous_messages
        assert result["messages"][: len(previous_messages)] == previous_messages
        if failure == "success":
            assert result["status"] == "completed"
            assert any(isinstance(message, SystemMessage) for message in model.calls[0])
        else:
            assert result["status"] == "failed"
            assert result["error"] is not None and result["error"]["code"] == "context_error"
            assert model.calls == []
        assert not any(isinstance(message, SystemMessage) for message in result["messages"])

    with open_sqlite_checkpointer(database) as saver:
        graph = build_minimal_graph(saver)
        assert graph.get_state(config).values["messages"] == result["messages"]
        recovered_model = ScriptedChatModel([AIMessage("recovered", id="a3")])
        recovered = run_session_turn(
            graph,
            session_id="session",
            content="continue",
            message_id="u3",
            context=RunContext(model=recovered_model),
        )
        assert recovered["status"] == "completed"
        assert recovered_model.calls[0][:-1] == tuple(result["messages"])


def test_tool_loop_rebuilds_context_with_valid_pairs_and_keeps_state(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("RULES", encoding="utf-8")
    request = AIMessage(
        "",
        id="call",
        tool_calls=[
            {"name": "add", "id": "sum", "args": {"left": 2, "right": 3}},
        ],
    )
    model = ScriptedChatModel([request, AIMessage("5", id="answer")])
    handler = RecordingAddHandler()
    initial = create_initial_state("old")
    initial["messages"] = [
        HumanMessage("old " * 100, id="u1"),
        AIMessage("old reply", id="a1"),
        HumanMessage("2+3", id="u2"),
    ]
    result = build_tool_graph().invoke(
        initial,
        context=RunContext(
            model=model,
            tools=ToolRegistry([create_add_tool(handler)]),
            context_config=ContextConfig(
                workspace_policy=WorkspacePathPolicy(tmp_path),
                active_path=".",
                max_bytes=400,
                compaction_threshold_tokens=1,
                summarizer=ModelSummarizer(FakeChatModel("old summary")),
            ),
        ),
    )
    assert result["status"] == "completed" and len(model.calls) == 2
    second = model.calls[1]
    assert isinstance(second[-1], ToolMessage) and second[-1].tool_call_id == "sum"
    assert second[-2] == request and second[-3].content == "2+3"
    assert result["messages"][:3] == initial["messages"]
    assert not any(isinstance(message, SystemMessage) for message in result["messages"])
