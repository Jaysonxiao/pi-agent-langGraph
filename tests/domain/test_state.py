"""State and message-reducer contract tests for M2."""

import pytest
from langchain_core.messages import HumanMessage, MessageLikeRepresentation
from langgraph.graph.message import add_messages

from pi_agent.domain.state import create_initial_state


def test_create_initial_state_preserves_user_content() -> None:
    state = create_initial_state("  keep my spacing  ", message_id="input-1")

    assert state["status"] == "ready"
    assert state["error"] is None
    assert state["messages"] == [HumanMessage(content="  keep my spacing  ", id="input-1")]


@pytest.mark.parametrize("content", ["", "   ", "\n\t"])
def test_create_initial_state_rejects_blank_content(content: str) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        create_initial_state(content)


def test_message_reducer_updates_same_id_without_duplication() -> None:
    existing: list[MessageLikeRepresentation] = [HumanMessage(content="draft", id="input-1")]
    correction: list[MessageLikeRepresentation] = [HumanMessage(content="corrected", id="input-1")]

    merged = add_messages(existing, correction)

    assert merged == [HumanMessage(content="corrected", id="input-1")]
