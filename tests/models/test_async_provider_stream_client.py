"""R2-D red tests for the async provider stream boundary."""

import asyncio
from collections.abc import AsyncIterator, Sequence

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models.async_adapter import CompatibleAsyncChatModel
from pi_agent.models.async_stream import collect_async_response
from pi_agent.models.usage import TokenUsage, UsageLedger


class StubStreamingClient:
    def __init__(self, chunks: Sequence[AIMessageChunk]) -> None:
        self._chunks = tuple(chunks)
        self.closed = False

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        del messages, config
        raise AssertionError("stream test must not use ainvoke")

    async def astream(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AsyncIterator[AIMessageChunk]:
        del messages, config
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def test_async_provider_stream_reaches_collector_and_preserves_usage() -> None:
    client = StubStreamingClient(
        [
            AIMessageChunk(content="hel"),
            AIMessageChunk(
                content="lo",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            ),
        ]
    )
    model = CompatibleAsyncChatModel(client)

    async def scenario() -> tuple[AIMessage, UsageLedger]:
        ledger = UsageLedger()
        message = await collect_async_response(
            model.astream(()),
            "stream:1",
            ledger,
        )
        await model.aclose()
        return message, ledger

    message, ledger = asyncio.run(scenario())

    assert message.content == "hello"
    assert ledger.total() == TokenUsage(2, 1, 3, "provider")
    assert client.closed is True
