"""Red tests for M7.3 ephemeral context assembly."""

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from pi_agent.context import WorkspaceInstruction, assemble_context_messages


def _instruction(path: str, content: str) -> WorkspaceInstruction:
    return WorkspaceInstruction(Path(path), content, len(content.encode()))


def test_prepends_one_system_message_and_preserves_history() -> None:
    history = (HumanMessage("hello"), AIMessage("world"))
    rules = (
        _instruction("C:/workspace/AGENTS.md", "root rule"),
        _instruction("C:/workspace/packages/AGENTS.md", "package rule"),
    )

    result = assemble_context_messages(history, rules)

    assert isinstance(result[0], SystemMessage)
    assert "C:/workspace/AGENTS.md" in result[0].content
    assert "root rule" in result[0].content
    assert "package rule" in result[0].content
    assert result[1:] == history


def test_existing_system_messages_remain_in_original_order() -> None:
    system = SystemMessage("base system")
    history = (system, HumanMessage("hello"))

    result = assemble_context_messages(history, (_instruction("rule.md", "rule"),))

    assert result[1:] == history
    assert result[0] is not system


def test_empty_rules_return_an_unchanged_tuple() -> None:
    history = (HumanMessage("hello"),)

    result = assemble_context_messages(history, ())

    assert result == history
    assert result is not history
