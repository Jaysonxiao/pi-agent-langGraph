"""Deterministic model used by tests and local learning exercises."""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, AnyMessage


class FakeChatModel:
    """Return a configured reply or raise a configured exception."""

    def __init__(self, reply: str = "fake reply", *, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[tuple[AnyMessage, ...]] = []

    def invoke(self, messages: Sequence[AnyMessage], /) -> AIMessage:
        """Record the input so tests can assert the model boundary."""
        self.calls.append(tuple(messages))
        if self.error is not None:
            raise self.error

        return AIMessage(content=self.reply, id=f"fake-assistant-{len(self.calls)}")


class ScriptedChatModel:
    """Return a fixed sequence of assistant messages for multi-turn graph tests."""

    def __init__(self, responses: Sequence[AIMessage]) -> None:
        if not responses:
            raise ValueError("ScriptedChatModel requires at least one response.")
        self.responses = tuple(responses)
        self.calls: list[tuple[AnyMessage, ...]] = []

    def invoke(self, messages: Sequence[AnyMessage], /) -> AIMessage:
        """Return the response matching the current invocation index."""
        self.calls.append(tuple(messages))
        response_index = len(self.calls) - 1
        if response_index >= len(self.responses):
            raise RuntimeError("ScriptedChatModel has no response for this invocation.")
        return self.responses[response_index]
