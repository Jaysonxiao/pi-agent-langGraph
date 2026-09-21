"""Model boundary used by graph nodes."""

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, AnyMessage


class ChatModel(Protocol):
    """Smallest model contract needed by M2."""

    def invoke(self, messages: Sequence[AnyMessage], /) -> AIMessage:
        """Return one assistant message for the supplied conversation."""
        ...
