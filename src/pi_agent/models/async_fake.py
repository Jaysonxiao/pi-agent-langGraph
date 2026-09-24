"""Deterministic native async model for M8.5 tests."""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig


class AsyncFakeChatModel:
    """Record async inputs and return one configured response or error."""

    def __init__(
        self,
        reply: AIMessage | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.reply = reply or AIMessage(content="async fake reply", id="async-fake-1")
        self.error = error
        self.calls: list[tuple[AnyMessage, ...]] = []
        self.configs: list[RunnableConfig | None] = []

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        """Record one native async invocation without starting a worker thread."""
        self.calls.append(tuple(messages))
        self.configs.append(config)
        if self.error is not None:
            raise self.error
        return self.reply
