"""Red tests for the learner-owned M8.6-R4 async response collector."""

import asyncio
from collections.abc import Iterable

import pytest
from langchain_core.messages import AIMessageChunk

from pi_agent.models.async_stream import collect_async_response
from pi_agent.models.usage import TokenUsage, UsageLedger


class TrackedAsyncChunks:
    """Provider-shaped chunk source with an explicit async close boundary."""

    def __init__(self, chunks: Iterable[AIMessageChunk], *, error_after: int | None = None) -> None:
        self._iterator = iter(chunks)
        self._error_after = error_after
        self._next_calls = 0
        self.close_calls = 0

    def __aiter__(self) -> "TrackedAsyncChunks":
        return self

    async def __anext__(self) -> AIMessageChunk:
        if self._error_after is not None and self._next_calls >= self._error_after:
            raise RuntimeError("synthetic stream failure")
        self._next_calls += 1
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        self.close_calls += 1


def test_collector_returns_complete_text_and_records_final_usage_once() -> None:
    raw = TrackedAsyncChunks(
        [
            AIMessageChunk(content="hel"),
            AIMessageChunk(
                content="lo",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            ),
        ]
    )
    ledger = UsageLedger()

    message = asyncio.run(collect_async_response(raw, "main:1", ledger))

    assert message.content == "hello"
    assert message.tool_calls == []
    assert ledger.total() == TokenUsage(2, 1, 3, "provider")
    assert raw.close_calls == 1


def test_collector_returns_tool_calls_only_after_all_fragments_arrive() -> None:
    raw = TrackedAsyncChunks(
        [
            AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"name": "read", "args": '{"path":"', "id": "call-read", "index": 0}
                ],
            ),
            AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": None, "args": 'README.md"}', "id": None, "index": 0}],
            ),
        ]
    )

    message = asyncio.run(collect_async_response(raw, "main:1", UsageLedger()))

    assert message.tool_calls == [
        {"name": "read", "args": {"path": "README.md"}, "id": "call-read", "type": "tool_call"}
    ]


def test_collector_records_unknown_when_only_a_nonterminal_chunk_has_usage() -> None:
    raw = TrackedAsyncChunks(
        [
            AIMessageChunk(
                content="first",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            ),
            AIMessageChunk(content="last"),
        ]
    )
    ledger = UsageLedger()

    message = asyncio.run(collect_async_response(raw, "main:1", ledger))

    assert message.content == "firstlast"
    assert ledger.total() == TokenUsage(None, None, None, "unknown")


def test_collector_closes_and_does_not_record_usage_when_stream_fails() -> None:
    raw = TrackedAsyncChunks(
        [
            AIMessageChunk(
                content="partial",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            )
        ],
        error_after=1,
    )
    ledger = UsageLedger()

    with pytest.raises(RuntimeError, match="synthetic stream failure"):
        asyncio.run(collect_async_response(raw, "main:1", ledger))

    assert ledger.total() == TokenUsage(None, None, None, "unknown")
    assert raw.close_calls == 1
