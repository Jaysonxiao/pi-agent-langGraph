"""Red tests for M7.5 compaction planning."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from pi_agent.context import CompactionPlan, plan_context_compaction


def test_plan_preserves_system_prefix_and_recent_suffix() -> None:
    system = SystemMessage("rules")
    old_user = HumanMessage("old user")
    old_ai = AIMessage("old answer")
    recent = HumanMessage("recent")

    result = plan_context_compaction((system, old_user, old_ai, recent), 1)

    assert result == CompactionPlan((system,), (old_user, old_ai), (recent,))


def test_plan_does_not_remove_history_when_it_fits() -> None:
    messages = (SystemMessage("rules"), HumanMessage("hello"))

    result = plan_context_compaction(messages, 2)

    assert result == CompactionPlan((messages[0],), (), (messages[1],))


def test_rejects_non_positive_recent_limit() -> None:
    with pytest.raises(ValueError, match="keep_recent_messages"):
        plan_context_compaction((), 0)


def test_plan_does_not_split_tool_call_and_tool_result() -> None:
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "read_file", "args": {}, "id": "call-1"}],
    )
    tool_result = ToolMessage(content="file content", tool_call_id="call-1")

    result = plan_context_compaction(
        (HumanMessage("read it"), tool_call, tool_result),
        keep_recent_messages=1,
    )

    assert result.removable == (HumanMessage("read it"),)
    assert result.recent == (tool_call, tool_result)
