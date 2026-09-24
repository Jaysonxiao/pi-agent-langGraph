"""Native asynchronous summary boundary for M8.5-R2."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.context.summarizer import SUMMARY_PROMPT
from pi_agent.models.async_base import AsyncChatModel


class AsyncSummarizer(Protocol):
    """Produce summary text without wrapping a synchronous model in a thread."""

    async def summarize(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class AsyncModelSummarizer:
    """Use the native async model protocol for context compaction."""

    model: AsyncChatModel

    async def summarize(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> str:
        """Return safe nonblank text without accepting model tool calls."""
        # 与同步 summarizer 同一套 JSON 数据投影, 不当指令执行.
        payload = json.dumps(
            [message.model_dump(mode="json") for message in messages],
            ensure_ascii=False,
        )
        # 直接 await, 把 RunnableConfig 原样前传; 取消由调用方处理.
        reply = await self.model.ainvoke(
            (SystemMessage(SUMMARY_PROMPT), HumanMessage(payload)),
            config,
        )
        if reply.tool_calls or not isinstance(reply.content, str) or not reply.content.strip():
            raise ValueError("Summary model must return nonblank text without tool calls.")
        return reply.content
