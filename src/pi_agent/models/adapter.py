"""Provider client adapter used by the M8.2 factory."""

from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, AnyMessage

from pi_agent.models.base import ChatModel
from pi_agent.models.config import ModelConfig
from pi_agent.models.errors import ModelProviderError


class ProviderClient(Protocol):
    """Small sync subset shared by an injected SDK client and the adapter."""

    def invoke(self, messages: Sequence[AnyMessage], /) -> object:
        """Return one provider response without exposing SDK types to the graph."""
        ...

    def close(self) -> None:
        """Release client resources; the stub and SDK wrapper must support this."""
        ...


class CompatibleChatModel(ChatModel):
    """Normalize one compatible provider client to the project ChatModel port."""

    def __init__(self, client: ProviderClient, config: ModelConfig) -> None:
        self._client = client
        self._config = config

    def invoke(self, messages: Sequence[AnyMessage], /) -> AIMessage:
        """Call the injected client and accept only a complete AIMessage."""
        try:
            response = self._client.invoke(messages)
        except Exception as exc:
            # The provider exception may contain URL headers or the API key.
            raise ModelProviderError("provider_call_failed", type(exc).__name__) from None
        if not isinstance(response, AIMessage):
            raise ModelProviderError("invalid_response", type(response).__name__)
        return response

    def close(self) -> None:
        """Close the owned provider client exactly once from the runner boundary."""
        self._client.close()
