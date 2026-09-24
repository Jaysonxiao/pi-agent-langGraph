"""M8.5 native async model-port tests."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models import AsyncFakeChatModel


def test_async_fake_awaits_and_forwards_runnable_config() -> None:
    model = AsyncFakeChatModel(AIMessage(content="done", id="async-result"))
    config = RunnableConfig(tags=["m85"])
    messages = (HumanMessage(content="hello", id="human-1"),)

    result = asyncio.run(model.ainvoke(messages, config))

    assert result == AIMessage(content="done", id="async-result")
    assert model.calls == [messages]
    assert model.configs == [config]


def test_async_fake_does_not_swallow_cancellation() -> None:
    model = AsyncFakeChatModel(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(model.ainvoke((HumanMessage(content="hello"),), None))
