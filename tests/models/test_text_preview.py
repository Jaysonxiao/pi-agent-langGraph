"""Text is provisional until the provider stream and tool arguments finish."""

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest
from langchain_core.messages import AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models.streaming import TextPreview, stream_response


class FragmentStream:
    def __init__(self, *, malformed: bool = False) -> None:
        self.closed = False
        self.malformed = malformed

    async def astream(
        self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
    ) -> AsyncIterator[AIMessageChunk]:
        try:
            yield AIMessageChunk(
                content="正在读取",
                tool_call_chunks=[
                    {"name": "read", "args": '{"path":"', "id": "read-call", "index": 0}
                ],
            )
            if not self.malformed:
                yield AIMessageChunk(
                    content="文件",
                    tool_call_chunks=[
                        {"name": None, "args": 'probe.txt"}', "id": None, "index": 0}
                    ],
                    usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                )
        finally:
            self.closed = True

    async def aclose(self) -> None:
        pass


def test_preview_complete_tool_assembly_identity_and_usage() -> None:
    previews: list[TextPreview] = []
    model = FragmentStream()

    async def observe(update: TextPreview) -> None:
        previews.append(update)

    reply = asyncio.run(stream_response(model, [], {}, observe))
    assert [item.text for item in previews] == ["", "正在读取", "正在读取文件", "正在读取文件"]
    assert previews[-1].status == "complete" and reply.id == previews[-1].message_id
    assert reply.content == "正在读取文件"
    assert reply.tool_calls[0]["args"] == {"path": "probe.txt"}
    assert reply.usage_metadata == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
    assert model.closed


def test_malformed_tool_stream_discards_preview_and_closes() -> None:
    previews: list[TextPreview] = []
    model = FragmentStream(malformed=True)

    async def observe(update: TextPreview) -> None:
        previews.append(update)

    with pytest.raises(ValueError):
        asyncio.run(stream_response(model, [], {}, observe))
    assert previews[-1].status == "discarded" and previews[-1].text == ""
    assert model.closed


def test_text_preview_is_utf8_bounded_without_truncating_committed_reply() -> None:
    class LongStream(FragmentStream):
        async def astream(
            self, messages: Sequence[AnyMessage], config: RunnableConfig | None = None, /
        ) -> AsyncIterator[AIMessageChunk]:
            yield AIMessageChunk(content="中" * 6000)

    previews: list[TextPreview] = []

    async def observe(update: TextPreview) -> None:
        previews.append(update)

    reply = asyncio.run(stream_response(LongStream(), [], {}, observe))
    assert reply.content == "中" * 6000
    assert previews[-1].truncated
    assert len(previews[-1].text.encode("utf-8")) <= 16384
