"""Adapters from LangGraph stream chunks to stable runtime events."""

from collections.abc import Iterable, Iterator, Mapping

from langchain_core.messages import BaseMessage

from pi_agent.closing import close_iterator
from pi_agent.events.custom import project_custom_chunk
from pi_agent.events.message import project_message_chunk
from pi_agent.events.stream import StreamEvent, project_stream_update


def project_update_chunks(
    chunks: Iterable[Mapping[str, object]],
) -> Iterator[StreamEvent]:
    """Project ordered ``stream_mode="updates"`` chunks."""

    iterator = iter(chunks)
    sequence = 0
    try:
        for chunk in iterator:
            # 保持 mapping 插入顺序; 不要按节点名排序.
            for node_name, update in chunk.items():
                if not isinstance(update, Mapping):
                    raise ValueError(
                        f"node update for {node_name!r} must be a mapping, "
                        f"got {type(update).__name__}"
                    )
                yield project_stream_update(node_name, update, sequence)
                sequence += 1
    finally:
        close_iterator(iterator)


def project_stream_chunks(
    chunks: Iterable[tuple[str, object]],
) -> Iterator[StreamEvent]:
    """Project a mixed ``updates/messages/custom`` LangGraph stream."""

    # CLI 拥有 graph.stream; 本层在 GeneratorExit/耗尽时把 close 传给 raw iterator.
    iterator = iter(chunks)
    sequence = 0
    try:
        for mode, chunk in iterator:
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
                # 一个 updates chunk 可含多个节点, 每个节点占用一个 sequence.
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
        close_iterator(iterator)
