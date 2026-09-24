"""Red tests for the learner-owned M8.5-R5 async provider adapter."""

import asyncio
from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models import CompatibleAsyncChatModel
from pi_agent.models.errors import ModelProviderError


class StubAsyncClient:
    def __init__(self, response: object, error: BaseException | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[tuple[AnyMessage, ...], RunnableConfig | None]] = []
        self.close_calls = 0

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        self.calls.append((tuple(messages), config))
        if self.error is not None:
            raise self.error
        return self.response

    async def aclose(self) -> None:
        self.close_calls += 1


def test_async_adapter_preserves_message_and_runnable_config() -> None:
    response = AIMessage(content="provider reply", id="provider-1")
    client = StubAsyncClient(response)
    model = CompatibleAsyncChatModel(client)
    messages = (HumanMessage(content="hello", id="human-1"),)
    config = RunnableConfig(tags=["m85-r5"])

    result = asyncio.run(model.ainvoke(messages, config))

    assert result is response
    assert client.calls == [(messages, config)]


def test_async_adapter_normalizes_provider_exception_without_secret() -> None:
    secret = "synthetic-async-secret"
    model = CompatibleAsyncChatModel(
        StubAsyncClient(AIMessage(content="unused"), RuntimeError(f"Bearer {secret}"))
    )

    with pytest.raises(ModelProviderError) as raised:
        asyncio.run(model.ainvoke((HumanMessage(content="hello"),), None))

    assert raised.value.code == "provider_call_failed"
    assert secret not in str(raised.value)


def test_async_adapter_rejects_non_ai_response_without_content_leak() -> None:
    secret = "synthetic-response-secret"
    model = CompatibleAsyncChatModel(StubAsyncClient({"content": secret}))

    with pytest.raises(ModelProviderError) as raised:
        asyncio.run(model.ainvoke((HumanMessage(content="hello"),), None))

    assert raised.value.code == "invalid_response"
    assert secret not in str(raised.value)


def test_async_adapter_propagates_cancellation() -> None:
    model = CompatibleAsyncChatModel(
        StubAsyncClient(AIMessage(content="unused"), asyncio.CancelledError())
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(model.ainvoke((HumanMessage(content="hello"),), None))


def test_async_adapter_closes_client() -> None:
    client = StubAsyncClient(AIMessage(content="unused"))

    asyncio.run(CompatibleAsyncChatModel(client).aclose())

    assert client.close_calls == 1
