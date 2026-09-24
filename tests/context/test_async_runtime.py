"""M8.5-R3 async context-preparation contracts."""

import asyncio

from langchain_core.messages import HumanMessage

from pi_agent.context import ContextConfig, prepare_model_messages_async


def test_async_preparation_delegates_without_an_async_summarizer() -> None:
    history = (HumanMessage(content="hello", id="human-1"),)

    result = asyncio.run(prepare_model_messages_async(history, ContextConfig(), None))

    assert result == history
    assert result is not history
