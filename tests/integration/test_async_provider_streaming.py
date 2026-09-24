"""Transport-level contracts for M8.9-R2-D provider streaming."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any, ClassVar

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from pi_agent.models import CompatibleAsyncChatModel, UsageLedger, collect_async_response
from pi_agent.models.config import ModelConfig, ModelOptions, resolve_model_config
from pi_agent.models.errors import ModelProviderError
from pi_agent.models.http_client import build_async_provider_client


class StubStreamResponse:
    def __init__(self, lines: Sequence[str], *, status_code: int = 200) -> None:
        self.status_code = status_code
        self._lines = tuple(lines)
        self.exited = False

    async def __aenter__(self) -> "StubStreamResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.exited = True

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class CancelledStreamResponse(StubStreamResponse):
    async def aiter_lines(self) -> AsyncIterator[str]:
        yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
        raise asyncio.CancelledError


class StubStreamingHttpClient:
    instances: ClassVar[list["StubStreamingHttpClient"]] = []
    next_response: ClassVar[StubStreamResponse]

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requests: list[tuple[str, str, object]] = []
        self.response = self.next_response
        self.closed = False
        self.instances.append(self)

    def stream(self, method: str, url: str, *, json: object) -> StubStreamResponse:
        self.requests.append((method, url, json))
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def _compatible_config() -> ModelConfig:
    return resolve_model_config(
        ModelOptions(),
        {
            "PI_AGENT_PROVIDER": "compatible",
            "PI_AGENT_MODEL": "test-model",
            "PI_AGENT_BASE_URL": "https://provider.example/v1",
            "PI_AGENT_API_KEY": "synthetic-secret",
        },
    )


def _install(monkeypatch: pytest.MonkeyPatch, lines: Sequence[str]) -> StubStreamResponse:
    response = StubStreamResponse(lines)
    StubStreamingHttpClient.instances.clear()
    StubStreamingHttpClient.next_response = response
    monkeypatch.setattr(httpx, "AsyncClient", StubStreamingHttpClient)
    return response


def test_stream_collects_text_and_terminal_usage_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _install(
        monkeypatch,
        (
            'data: {"choices":[{"delta":{"content":"hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":2,'
            '"completion_tokens":1,"total_tokens":3}}',
            "data: [DONE]",
        ),
    )

    async def scenario() -> tuple[AIMessage, UsageLedger]:
        client = build_async_provider_client(_compatible_config())
        model = CompatibleAsyncChatModel(client)
        ledger = UsageLedger()
        try:
            message = await collect_async_response(
                model.astream((HumanMessage(content="hello"),)), "attempt-1", ledger
            )
            return message, ledger
        finally:
            await model.aclose()

    message, ledger = asyncio.run(scenario())

    assert message.content == "hello"
    assert ledger.total().total_tokens == 3
    stub = StubStreamingHttpClient.instances[0]
    assert stub.requests[0][2] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert response.exited is True
    assert stub.closed is True


def test_stream_assembles_tool_call_only_after_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(
        monkeypatch,
        (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"id":"call-read","function":{"name":"read",'
            '"arguments":"{\\"path\\":\\""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            '"function":{"arguments":"README.md\\"}"}}]}}]}',
            "data: [DONE]",
        ),
    )

    async def scenario() -> AIMessage:
        client = build_async_provider_client(_compatible_config())
        model = CompatibleAsyncChatModel(client)
        try:
            return await collect_async_response(model.astream(()), "attempt-2", UsageLedger())
        finally:
            await model.aclose()

    message = asyncio.run(scenario())
    assert message.tool_calls == [
        {
            "name": "read",
            "args": {"path": "README.md"},
            "id": "call-read",
            "type": "tool_call",
        }
    ]


def test_stream_rejects_eof_without_done_and_closes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _install(
        monkeypatch,
        ('data: {"choices":[{"delta":{"content":"partial"}}]}',),
    )

    async def scenario() -> None:
        client = build_async_provider_client(_compatible_config())
        model = CompatibleAsyncChatModel(client)
        try:
            with pytest.raises(ModelProviderError) as raised:
                await collect_async_response(model.astream(()), "attempt-3", UsageLedger())
            assert raised.value.exception_type == "IncompleteStream"
        finally:
            await model.aclose()

    asyncio.run(scenario())
    assert response.exited is True


def test_stream_rejects_invalid_json_without_body_or_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, ("data: Bearer synthetic-secret {",))

    async def scenario() -> None:
        client = build_async_provider_client(_compatible_config())
        model = CompatibleAsyncChatModel(client)
        try:
            with pytest.raises(ModelProviderError) as raised:
                await collect_async_response(model.astream(()), "attempt-4", UsageLedger())
            assert raised.value.code == "invalid_response"
            assert "synthetic-secret" not in str(raised.value)
        finally:
            await model.aclose()

    asyncio.run(scenario())


def test_stream_cancellation_closes_response_without_recording_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = CancelledStreamResponse(())
    StubStreamingHttpClient.instances.clear()
    StubStreamingHttpClient.next_response = response
    monkeypatch.setattr(httpx, "AsyncClient", StubStreamingHttpClient)

    async def scenario() -> UsageLedger:
        client = build_async_provider_client(_compatible_config())
        model = CompatibleAsyncChatModel(client)
        ledger = UsageLedger()
        try:
            with pytest.raises(asyncio.CancelledError):
                await collect_async_response(model.astream(()), "attempt-5", ledger)
            return ledger
        finally:
            await model.aclose()

    ledger = asyncio.run(scenario())
    assert ledger.total().source == "unknown"
    assert ledger.total().total_tokens is None
    assert response.exited is True
