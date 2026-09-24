"""Red tests for the learner-owned M8.5-R2 async summary adapter."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.context import AsyncModelSummarizer
from pi_agent.context.summarizer import SUMMARY_PROMPT
from pi_agent.models import AsyncFakeChatModel


def test_async_summary_forwards_serialized_history_and_config() -> None:
    model = AsyncFakeChatModel(AIMessage(content="Earlier setup was completed."))
    summarizer = AsyncModelSummarizer(model)
    config = RunnableConfig(tags=["m85-r2"])

    result = asyncio.run(
        summarizer.summarize(
            (HumanMessage(content="old goal", id="old-1"),),
            config,
        )
    )

    assert result == "Earlier setup was completed."
    assert model.configs == [config]
    assert isinstance(model.calls[0][0], SystemMessage)
    assert model.calls[0][0].content == SUMMARY_PROMPT
    assert isinstance(model.calls[0][1], HumanMessage)
    payload = model.calls[0][1].content
    assert isinstance(payload, str)
    decoded = json.loads(payload)
    assert decoded[0]["content"] == "old goal"
    assert decoded[0]["id"] == "old-1"


@pytest.mark.parametrize(
    "reply",
    [
        AIMessage(content=" "),
        AIMessage(content=[{"type": "text", "text": "structured"}]),
        AIMessage(
            content="",
            tool_calls=[{"name": "read", "args": {"path": "README.md"}, "id": "call-1"}],
        ),
    ],
)
def test_async_summary_rejects_invalid_reply(reply: AIMessage) -> None:
    summarizer = AsyncModelSummarizer(AsyncFakeChatModel(reply))

    with pytest.raises(ValueError, match="nonblank text without tool calls"):
        asyncio.run(summarizer.summarize((HumanMessage(content="old"),), None))


def test_async_summary_propagates_cancellation() -> None:
    summarizer = AsyncModelSummarizer(AsyncFakeChatModel(error=asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(summarizer.summarize((HumanMessage(content="old"),), None))
