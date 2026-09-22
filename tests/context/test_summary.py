"""Red tests for M7.6 temporary compaction summary insertion."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from pi_agent.context import CompactionPlan, apply_compaction_summary


def test_inserts_summary_between_system_prefix_and_recent_history() -> None:
    system = SystemMessage("rules")
    recent = HumanMessage("recent")
    plan = CompactionPlan((system,), (HumanMessage("old"),), (recent,))

    result = apply_compaction_summary(plan, "Earlier discussion covered setup.")

    assert result[0] is system
    assert isinstance(result[1], SystemMessage)
    assert "Earlier discussion covered setup." in result[1].content
    assert result[2:] == (recent,)


def test_does_not_insert_empty_summary_when_nothing_is_removable() -> None:
    recent = AIMessage("recent")
    plan = CompactionPlan((), (), (recent,))

    result = apply_compaction_summary(plan, "unused")

    assert result == (recent,)


def test_rejects_blank_summary_when_history_was_removed() -> None:
    plan = CompactionPlan((), (HumanMessage("old"),), ())

    with pytest.raises(ValueError, match="summary"):
        apply_compaction_summary(plan, " ")
