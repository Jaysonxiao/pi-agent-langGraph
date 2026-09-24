"""Offline contract tests for the M8.9-R2-A compatible HTTP client."""

import asyncio
from typing import Any, ClassVar

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from pi_agent.models.config import ModelConfig, ModelOptions, resolve_model_config
from pi_agent.models.errors import ModelProviderError
from pi_agent.models.http_client import build_async_provider_client


class StubResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class StubAsyncClient:
    instances: ClassVar[list["StubAsyncClient"]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.posts: list[tuple[str, object]] = []
        self.response = StubResponse(
            200,
            {"choices": [{"message": {"content": "offline reply"}}]},
        )
        self.closed = False
        self.instances.append(self)

    async def post(self, url: str, *, json: object) -> StubResponse:
        self.posts.append((url, json))
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def compatible_config() -> ModelConfig:
    return resolve_model_config(
        ModelOptions(),
        {
            "PI_AGENT_PROVIDER": "compatible",
            "PI_AGENT_MODEL": "test-model",
            "PI_AGENT_BASE_URL": "https://provider.example/v1",
            "PI_AGENT_API_KEY": "synthetic-secret",
        },
    )


def test_client_posts_openai_compatible_payload_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    StubAsyncClient.instances.clear()
    monkeypatch.setattr(httpx, "AsyncClient", StubAsyncClient)

    client = build_async_provider_client(compatible_config())
    result = asyncio.run(client.ainvoke((HumanMessage(content="hello"),)))
    asyncio.run(client.aclose())

    stub = StubAsyncClient.instances[0]
    assert stub.kwargs["headers"] == {
        "Authorization": "Bearer synthetic-secret",
        "Content-Type": "application/json",
    }
    assert stub.kwargs["timeout"] == 30.0
    assert stub.posts == [
        (
            "https://provider.example/v1/chat/completions",
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
    ]
    assert result == AIMessage(content="offline reply")
    assert stub.closed is True


def test_client_hides_http_failure_body_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    StubAsyncClient.instances.clear()
    monkeypatch.setattr(httpx, "AsyncClient", StubAsyncClient)
    client = build_async_provider_client(compatible_config())
    StubAsyncClient.instances[0].response = StubResponse(
        401,
        {"error": "Bearer synthetic-secret rejected"},
    )

    with pytest.raises(ModelProviderError) as raised:
        asyncio.run(client.ainvoke((HumanMessage(content="hello"),)))

    assert raised.value.code == "provider_call_failed"
    assert "synthetic-secret" not in str(raised.value)
    asyncio.run(client.aclose())


def test_client_rejects_incomplete_response_without_body_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    StubAsyncClient.instances.clear()
    monkeypatch.setattr(httpx, "AsyncClient", StubAsyncClient)
    client = build_async_provider_client(compatible_config())
    StubAsyncClient.instances[0].response = StubResponse(
        200,
        {"choices": []},
    )

    with pytest.raises(ModelProviderError) as raised:
        asyncio.run(client.ainvoke((HumanMessage(content="hello"),)))

    assert raised.value.code == "invalid_response"
    assert "choices" not in str(raised.value)
    asyncio.run(client.aclose())


def test_client_normalizes_provider_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """R2-B contract: preserve one provider function call for the graph layer."""

    class ToolCallClient(StubAsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.response = StubResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "read",
                                            "arguments": '{"path":"README.md"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
            )

    StubAsyncClient.instances.clear()
    # The learner should keep the same constructor boundary while extending
    # response normalization to tool calls.
    monkeypatch.setattr(httpx, "AsyncClient", ToolCallClient)
    client = build_async_provider_client(compatible_config())
    result = asyncio.run(client.ainvoke((HumanMessage(content="read README"),)))
    asyncio.run(client.aclose())

    assert isinstance(result, AIMessage)
    assert result.content == ""
    assert result.tool_calls == [
        {
            "name": "read",
            "args": {"path": "README.md"},
            "id": "call-1",
            "type": "tool_call",
        }
    ]


def test_client_replays_assistant_tool_call_before_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second provider turn must retain the assistant call envelope."""
    StubAsyncClient.instances.clear()
    monkeypatch.setattr(httpx, "AsyncClient", StubAsyncClient)
    client = build_async_provider_client(compatible_config())
    assistant = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "read",
                "args": {"path": "README.md"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )

    asyncio.run(
        client.ainvoke(
            (
                HumanMessage(content="read README"),
                assistant,
                ToolMessage(content="README content", tool_call_id="call-1"),
            )
        )
    )
    asyncio.run(client.aclose())

    payload = StubAsyncClient.instances[0].posts[0][1]
    assert isinstance(payload, dict)
    assert payload["messages"] == [
        {"role": "user", "content": "read README"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "read",
                        "arguments": '{"path":"README.md"}',
                    },
                }
            ],
        },
        {"role": "tool", "content": "README content", "tool_call_id": "call-1"},
    ]
