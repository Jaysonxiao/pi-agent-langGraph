"""Red tests for M7.4 deterministic context budgeting."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from pi_agent.context import BoundedContext, fit_context_messages


def test_budget_keeps_all_messages_when_they_fit() -> None:
    messages = (SystemMessage("rules"), HumanMessage("hello"), AIMessage("world"))

    result = fit_context_messages(messages, max_bytes=100)

    assert result == BoundedContext(messages, 15, 15, 0, 100, False)


def test_budget_drops_oldest_history_but_preserves_system_messages() -> None:
    system = SystemMessage("rules")
    old = HumanMessage("old")
    newest = AIMessage("newest")

    result = fit_context_messages((system, old, newest), max_bytes=11)

    assert result.messages == (system, newest)
    assert result.dropped_messages == 1
    assert result.over_budget is False


def test_system_message_can_make_context_unavoidably_over_budget() -> None:
    system = SystemMessage("long rules")

    result = fit_context_messages((system, HumanMessage("hello")), max_bytes=4)

    assert result.messages == (system,)
    assert result.dropped_messages == 1
    assert result.over_budget is True


def test_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        fit_context_messages((), max_bytes=0)


def test_counts_structured_message_content_instead_of_silently_zero() -> None:
    message = HumanMessage(content=[{"type": "text", "text": "你好"}])

    result = fit_context_messages((message,), max_bytes=1)

    assert result.original_bytes > 0
    assert result.messages == ()
    assert result.dropped_messages == 1
