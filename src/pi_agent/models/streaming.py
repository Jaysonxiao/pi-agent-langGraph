"""Optional text previews, separate from durable messages and lifecycle telemetry."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models.async_adapter import AsyncStreamingProviderClient
from pi_agent.models.async_stream import collect_async_response
from pi_agent.models.usage import UsageLedger


@dataclass(frozen=True, slots=True)
class TextPreview:
    message_id: str
    text: str
    status: Literal["streaming", "complete", "discarded"]
    truncated: bool = False


TextObserver = Callable[[TextPreview], Awaitable[None]]


async def stream_response(
    model: AsyncStreamingProviderClient,
    messages: Sequence[AnyMessage],
    config: RunnableConfig,
    observer: TextObserver,
) -> AIMessage:
    """Preview text, but commit only a complete response with validated tool calls."""
    message_id = uuid4().hex
    text = ""
    truncated = False
    await observer(TextPreview(message_id, text, "streaming"))
    raw = model.astream(messages, config)

    async def chunks() -> AsyncIterator[AIMessageChunk]:
        nonlocal text, truncated
        try:
            async for chunk in raw:
                if isinstance(chunk.content, str) and chunk.content:
                    encoded = (text + chunk.content).encode("utf-8", errors="replace")
                    truncated = truncated or len(encoded) > 16384
                    text = encoded[:16384].decode("utf-8", errors="ignore")
                    await observer(TextPreview(message_id, text, "streaming", truncated))
                yield chunk
        finally:
            close = getattr(raw, "aclose", None)
            if callable(close):
                await close()

    try:
        reply = await collect_async_response(chunks(), message_id, UsageLedger())
        reply.id = message_id
        await observer(TextPreview(message_id, text, "complete", truncated))
        return reply
    except BaseException:
        await observer(TextPreview(message_id, "", "discarded"))
        raise
