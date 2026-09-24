"""Red tests for the learner-owned M8.6-R1 async stream adapter."""

import asyncio
from collections.abc import Iterable

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from pi_agent.events import StreamEvent, project_async_stream_chunks


class TrackedAsyncChunks:
    """Minimal raw async stream that exposes whether its resource was closed."""

    def __init__(self, chunks: Iterable[tuple[str, object]]) -> None:
        self._iterator = iter(chunks)
        self.close_calls = 0

    def __aiter__(self) -> "TrackedAsyncChunks":
        return self

    async def __anext__(self) -> tuple[str, object]:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.close_calls += 1


def test_async_adapter_preserves_modes_order_sequence_and_closes() -> None:
    raw = TrackedAsyncChunks(
        [
            (
                "custom",
                {
                    "type": "progress",
                    "node": "model",
                    "message": "calling model",
                    "completed": 0,
                    "total": 1,
                },
            ),
            (
                "messages",
                (AIMessageChunk(content="hel", id="chunk-1"), {"langgraph_node": "model"}),
            ),
            (
                "updates",
                {
                    "model": {"status": "completed"},
                    "tools": {"status": "ready", "tool_rounds": 1},
                },
            ),
        ]
    )

    async def collect() -> list[StreamEvent]:
        return [event async for event in project_async_stream_chunks(raw)]

    events = asyncio.run(collect())

    assert [event.sequence for event in events] == [0, 1, 2, 3]
    assert [event.kind for event in events] == ["progress", "message", "state_update", "tool"]
    assert raw.close_calls == 1


def test_async_adapter_closes_raw_stream_when_consumer_stops_early() -> None:
    raw = TrackedAsyncChunks(
        [
            (
                "messages",
                (AIMessage(content="first", id="first"), {"langgraph_node": "model"}),
            ),
            (
                "messages",
                (AIMessage(content="second", id="second"), {"langgraph_node": "model"}),
            ),
        ]
    )

    async def consume_one_then_close() -> StreamEvent:
        projected = project_async_stream_chunks(raw)
        first = await anext(projected)
        await projected.aclose()
        return first

    first = asyncio.run(consume_one_then_close())

    assert first.payload["content"] == "first"
    assert raw.close_calls == 1


def test_async_adapter_closes_raw_stream_when_payload_is_invalid() -> None:
    raw = TrackedAsyncChunks([("messages", ("not-a-message", {}))])

    async def collect_invalid() -> None:
        with pytest.raises(ValueError, match="messages"):
            _ = [event async for event in project_async_stream_chunks(raw)]

    asyncio.run(collect_invalid())

    assert raw.close_calls == 1
