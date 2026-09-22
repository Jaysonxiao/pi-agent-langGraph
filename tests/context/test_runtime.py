"""Unit tests for the M7 model-context pipeline."""

from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from pi_agent.context import ContextConfig, prepare_model_messages
from pi_agent.security import WorkspacePathPolicy


def test_prepares_workspace_rules_without_mutating_history(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root rule", encoding="utf-8")
    active = tmp_path / "main.py"
    active.write_text("pass", encoding="utf-8")
    history = (HumanMessage("hello"),)

    result = prepare_model_messages(
        history,
        ContextConfig(
            workspace_policy=WorkspacePathPolicy(tmp_path),
            active_path=str(active),
        ),
    )

    assert isinstance(result[0], SystemMessage)
    assert "root rule" in result[0].content
    assert history == (HumanMessage("hello"),)


def test_default_config_returns_a_new_tuple_with_same_messages() -> None:
    history = (HumanMessage("hello"),)

    result = prepare_model_messages(history, ContextConfig())

    assert result == history
    assert result is not history


def test_summary_config_requires_recent_message_limit() -> None:
    with pytest.raises(ValueError, match="keep_recent_messages"):
        ContextConfig(summary="old context")


def test_pipeline_injects_summary_after_compaction_plan() -> None:
    history = (HumanMessage("old"), HumanMessage("recent"))

    result = prepare_model_messages(
        history,
        ContextConfig(summary="Earlier context", keep_recent_messages=1),
    )

    assert isinstance(result[0], SystemMessage)
    assert result[0].content == "Earlier context"
    assert result[1:] == (history[1],)
