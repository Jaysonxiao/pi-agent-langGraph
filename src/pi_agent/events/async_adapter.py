"""Async projection boundary for native LangGraph-style stream chunks."""

from collections.abc import AsyncGenerator, AsyncIterable, Mapping

from langchain_core.messages import BaseMessage

from pi_agent.events.custom import project_custom_chunk
from pi_agent.events.message import project_message_chunk
from pi_agent.events.stream import StreamEvent, project_stream_update


async def project_async_stream_chunks(
    chunks: AsyncIterable[tuple[str, object]],
    /,
) -> AsyncGenerator[StreamEvent, None]:
    """Project a mixed async ``updates/messages/custom`` stream safely."""
    # 先拿到 raw async iterator, 才能在所有退出路径上精确 aclose 一次.
    iterator = aiter(chunks)
    sequence = 0
    try:
        async for mode, chunk in iterator:
            if mode == "custom":
                if not isinstance(chunk, Mapping):
                    raise ValueError("custom chunk must be a mapping")
                yield project_custom_chunk(chunk, sequence)
                sequence += 1
                continue

            if mode == "messages":
                if (
                    not isinstance(chunk, tuple)
                    or len(chunk) != 2
                    or not isinstance(chunk[0], BaseMessage)
                    or not isinstance(chunk[1], Mapping)
                ):
                    raise ValueError("messages chunk must be a (BaseMessage, mapping) tuple")
                message, metadata = chunk
                yield project_message_chunk(message, metadata, sequence)
                sequence += 1
                continue

            if mode == "updates":
                if not isinstance(chunk, Mapping):
                    raise ValueError("updates chunk must be a mapping")
                # 一个 updates chunk 可含多个节点, 各自占用一个全局 sequence.
                for node_name, update in chunk.items():
                    if not isinstance(node_name, str) or not node_name:
                        raise ValueError("updates node name must be a non-empty string")
                    if not isinstance(update, Mapping):
                        raise ValueError(
                            f"node update for {node_name!r} must be a mapping, "
                            f"got {type(update).__name__}"
                        )
                    yield project_stream_update(node_name, update, sequence)
                    sequence += 1
                continue

            raise ValueError(f"unknown stream mode {mode!r}")
    finally:
        # 耗尽、投影失败、消费者 aclose/取消都走这里; 不吞 CancelledError.
        aclose = getattr(iterator, "aclose", None)
        if callable(aclose):
            await aclose()
