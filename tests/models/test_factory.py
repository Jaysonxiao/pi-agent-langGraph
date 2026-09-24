"""M8.2 contract tests; only build_model remains learner-owned."""

from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from pi_agent.models.adapter import CompatibleChatModel, ProviderClient
from pi_agent.models.config import ModelConfig, ModelOptions, resolve_model_config
from pi_agent.models.errors import ModelFactoryError, ModelProviderError
from pi_agent.models.factory import build_model

SECRET = "synthetic-m82-secret"


class StubClient(ProviderClient):
    def __init__(
        self, response: object = AIMessage(content="ok"), error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[AnyMessage, ...]] = []
        self.close_calls = 0

    def invoke(self, messages: Sequence[AnyMessage], /) -> object:
        self.calls.append(tuple(messages))
        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        self.close_calls += 1


def compatible_config() -> ModelConfig:
    return resolve_model_config(
        ModelOptions(
            provider="compatible",
            model="stub-model",
            base_url="https://provider.example/v1",
            api_key_env="STUB_KEY",
        ),
        {"STUB_KEY": SECRET},
    )


def test_adapter_preserves_complete_ai_message_and_input() -> None:
    client = StubClient(AIMessage(content="provider reply", id="provider-1"))
    adapter = CompatibleChatModel(client, compatible_config())
    messages = (HumanMessage(content="hello", id="human-1"),)

    result = adapter.invoke(messages)

    assert result.content == "provider reply"
    assert result.id == "provider-1"
    assert client.calls == [messages]


def test_adapter_rejects_non_ai_response_without_provider_details() -> None:
    client = StubClient({"content": SECRET})
    adapter = CompatibleChatModel(client, compatible_config())

    with pytest.raises(ModelProviderError) as caught:
        adapter.invoke((HumanMessage(content="hello"),))

    assert caught.value.code == "invalid_response"
    assert SECRET not in str(caught.value)


def test_adapter_normalizes_provider_exception_without_secret() -> None:
    client = StubClient(error=RuntimeError(f"Authorization: Bearer {SECRET}"))
    adapter = CompatibleChatModel(client, compatible_config())

    with pytest.raises(ModelProviderError) as caught:
        adapter.invoke((HumanMessage(content="hello"),))

    assert caught.value.code == "provider_call_failed"
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)


def test_adapter_closes_owned_client() -> None:
    client = StubClient()
    CompatibleChatModel(client, compatible_config()).close()
    assert client.close_calls == 1


def test_factory_fake_does_not_need_a_client() -> None:
    config = resolve_model_config(ModelOptions(), {})
    calls = 0

    def unexpected_factory(_: ModelConfig) -> StubClient:
        nonlocal calls
        calls += 1
        return StubClient()

    # Learner implementation: fake should return FakeChatModel and calls stay zero.
    model = build_model(config, client_factory=unexpected_factory)
    assert model.__class__.__name__ == "FakeChatModel"
    assert calls == 0


def test_factory_compatible_passes_config_to_injected_client_factory() -> None:
    config = compatible_config()
    created: list[ModelConfig] = []
    client = StubClient(AIMessage(content="ok"))

    def client_factory(received: ModelConfig) -> StubClient:
        created.append(received)
        return client

    model = build_model(config, client_factory=client_factory)

    assert isinstance(model, CompatibleChatModel)
    assert created == [config]
    assert model.invoke((HumanMessage(content="hello"),)).content == "ok"


def test_factory_requires_client_factory_for_compatible() -> None:
    with pytest.raises(ModelFactoryError):
        build_model(compatible_config())


def test_factory_does_not_expose_client_creation_exception() -> None:
    config = compatible_config()

    def failing_factory(_: ModelConfig) -> StubClient:
        raise RuntimeError(f"transport key={SECRET}")

    with pytest.raises(ModelFactoryError) as caught:
        build_model(config, client_factory=failing_factory)

    assert SECRET not in str(caught.value)
