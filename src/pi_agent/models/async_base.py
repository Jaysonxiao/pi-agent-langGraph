"""Native asynchronous model port introduced by M8.5."""

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig


class AsyncChatModel(Protocol):
    """Small async model contract required by the LangGraph model node."""

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        """Return one complete assistant message without a thread wrapper."""
        ...
