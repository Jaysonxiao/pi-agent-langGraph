"""Completion boundary for one native async provider response stream."""

from collections.abc import AsyncIterable, Mapping

from langchain_core.messages import AIMessage, AIMessageChunk

from pi_agent.events.tool_calls import assemble_tool_call_message
from pi_agent.models.usage import UsageLedger


async def collect_async_response(
    chunks: AsyncIterable[AIMessageChunk],
    attempt_id: str,
    usage_ledger: UsageLedger,
    /,
) -> AIMessage:
    """Collect one complete response and record usage only after stream success."""
    iterator = aiter(chunks)
    collected: list[AIMessageChunk] = []
    try:
        async for chunk in iterator:
            collected.append(chunk)
        if not collected:
            raise ValueError("response stream is empty")

        # 半截文本/tool call 不得提前交出去; 只在自然耗尽后装配完整消息.
        text_parts: list[str] = []
        has_tool_fragments = False
        for chunk in collected:
            if isinstance(chunk.content, str):
                text_parts.append(chunk.content)
            if chunk.tool_call_chunks:
                has_tool_fragments = True

        tool_calls: list[object] = []
        if has_tool_fragments:
            tool_calls = list(assemble_tool_call_message(collected).tool_calls)

        message = AIMessage(content="".join(text_parts), tool_calls=tool_calls)
        # 只认最后一个 chunk 的 usage; 前段临时计数不当最终计费, 缺失则记 unknown.
        terminal_usage = collected[-1].usage_metadata
        usage_ledger.record_final(
            attempt_id,
            terminal_usage if isinstance(terminal_usage, Mapping) else None,
        )
        return message
    finally:
        aclose = getattr(iterator, "aclose", None)
        if callable(aclose):
            await aclose()
