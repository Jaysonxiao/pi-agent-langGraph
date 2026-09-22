"""Integration tests for M7 context preparation at the model boundary."""

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from pi_agent.context import ContextConfig
from pi_agent.domain import create_initial_state
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import FakeChatModel
from pi_agent.security import WorkspacePathPolicy


def test_model_receives_derived_context_but_state_keeps_original_history(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use the project rules.", encoding="utf-8")
    active = tmp_path / "src" / "main.py"
    active.parent.mkdir()
    active.write_text("print('ok')", encoding="utf-8")
    model = FakeChatModel("done")

    result = build_minimal_graph().invoke(
        create_initial_state("hello", message_id="input-1"),
        context=RunContext(
            model=model,
            context_config=ContextConfig(
                workspace_policy=WorkspacePathPolicy(tmp_path),
                active_path=str(active),
            ),
        ),
    )

    assert isinstance(model.calls[0][0], SystemMessage)
    assert "Use the project rules." in model.calls[0][0].content
    assert model.calls[0][-1] == HumanMessage(content="hello", id="input-1")
    assert result["messages"] == [
        HumanMessage(content="hello", id="input-1"),
        AIMessage(content="done", id="fake-assistant-1"),
    ]
    assert all(message.content != "Use the project rules." for message in result["messages"])
