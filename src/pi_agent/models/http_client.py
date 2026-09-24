"""OpenAI-compatible async HTTP client for the M8.9 provider boundary."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import cast

import httpx
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.messages.tool import ToolCallChunk
from langchain_core.runnables import RunnableConfig

from pi_agent.models.async_adapter import AsyncProviderClient
from pi_agent.models.config import ModelConfig
from pi_agent.models.errors import ModelFactoryError, ModelProviderError


class CompatibleHttpClient:
    """One owned httpx client mapped to the project AsyncProviderClient port."""

    def __init__(self, config: ModelConfig) -> None:
        if config.base_url is None or config.model is None or config.api_key is None:
            raise ModelFactoryError()
        self._model = config.model
        self._endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
        self._tools: tuple[Mapping[str, object], ...] = ()
        # 密钥只放进 Authorization, 不写入日志或异常正文.
        self._http = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {config.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            timeout=config.timeout_seconds,
        )

    def bind_tools(self, tools: Sequence[Mapping[str, object]]) -> None:
        """Install a stable, caller-authorized schema set for both request modes."""
        self._tools = tuple(tools)

    def _request_body(self, messages: Sequence[AnyMessage]) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [_to_compat_message(item) for item in messages],
        }
        if self._tools:
            body["tools"] = list(self._tools)
        return body

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        del config
        try:
            response = await self._http.post(
                self._endpoint,
                json=self._request_body(messages),
            )
        except httpx.TimeoutException:
            raise ModelProviderError("provider_call_failed", "TimeoutException") from None
        except httpx.HTTPError:
            raise ModelProviderError("provider_call_failed", "HTTPError") from None
        if response.status_code < 200 or response.status_code >= 300:
            raise ModelProviderError(
                "provider_call_failed", "HTTPStatusError", status_code=response.status_code
            )
        try:
            payload = response.json()
        except ValueError:
            raise ModelProviderError("invalid_response", "JSONDecodeError") from None
        return _ai_message_from_payload(payload)

    async def astream(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AsyncIterator[AIMessageChunk]:
        """Yield normalized chunks from one OpenAI-compatible SSE response."""
        del config
        saw_done = False
        try:
            async with self._http.stream(
                "POST",
                self._endpoint,
                json={
                    **self._request_body(messages),
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise ModelProviderError(
                        "provider_call_failed", "HTTPStatusError", status_code=response.status_code
                    )
                async for line in response.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        raise ModelProviderError("invalid_response", "JSONDecodeError") from None
                    yield _ai_chunk_from_payload(payload)
                if not saw_done:
                    raise ModelProviderError("provider_call_failed", "IncompleteStream")
        except asyncio.CancelledError:
            raise
        except ModelProviderError:
            raise
        except httpx.TimeoutException:
            raise ModelProviderError("provider_call_failed", "TimeoutException") from None
        except httpx.HTTPError:
            raise ModelProviderError("provider_call_failed", "HTTPError") from None

    async def aclose(self) -> None:
        await self._http.aclose()


def build_async_provider_client(config: ModelConfig) -> AsyncProviderClient:
    """Build the configured async client without exposing SDK types to the graph."""
    if config.provider != "compatible":
        raise ValueError("Async HTTP client requires the compatible provider.")
    return CompatibleHttpClient(config)


def _to_compat_message(message: AnyMessage) -> dict[str, object]:
    """Project LangChain messages to the Chat Completions wire format."""
    if isinstance(message, HumanMessage):
        return {"role": "user", "content": _text_content(message)}
    if isinstance(message, SystemMessage):
        return {"role": "system", "content": _text_content(message)}
    if isinstance(message, ToolMessage):
        return {
            "role": "tool",
            "content": _text_content(message),
            "tool_call_id": message.tool_call_id,
        }
    if isinstance(message, AIMessage):
        projected: dict[str, object] = {
            "role": "assistant",
            "content": _text_content(message),
        }
        if message.tool_calls:
            projected["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(
                            call["args"], ensure_ascii=False, separators=(",", ":")
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        return projected
    raise ModelProviderError("invalid_response", type(message).__name__)


def _text_content(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return ""


def _ai_message_from_payload(payload: object) -> AIMessage:
    """Accept a complete assistant message; never put the body in errors."""
    if not isinstance(payload, dict):
        raise ModelProviderError("invalid_response", type(payload).__name__)
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelProviderError("invalid_response", type(choices).__name__)
    first = choices[0]
    if not isinstance(first, dict):
        raise ModelProviderError("invalid_response", type(first).__name__)
    message = first.get("message")
    if not isinstance(message, dict):
        raise ModelProviderError("invalid_response", type(message).__name__)
    content = message.get("content")
    # 兼容服务在纯 tool_calls 时会给 content: null.
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    else:
        raise ModelProviderError("invalid_response", type(content).__name__)
    raw_calls = message.get("tool_calls")
    usage = _usage_metadata(payload.get("usage"))
    if raw_calls is None:
        return AIMessage(content=text, usage_metadata=usage)
    return AIMessage(
        content=text,
        tool_calls=_parse_tool_calls(raw_calls),
        usage_metadata=usage,
    )


def _parse_tool_calls(raw_calls: object) -> list[dict[str, object]]:
    """Map provider function calls to LangChain tool_calls without leaking args."""
    if not isinstance(raw_calls, list):
        raise ModelProviderError("invalid_response", type(raw_calls).__name__)
    parsed: list[dict[str, object]] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            raise ModelProviderError("invalid_response", type(item).__name__)
        call_id = item.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise ModelProviderError("invalid_response", type(call_id).__name__)
        function = item.get("function")
        if not isinstance(function, dict):
            raise ModelProviderError("invalid_response", type(function).__name__)
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ModelProviderError("invalid_response", type(name).__name__)
        parsed.append(
            {
                "name": name,
                "args": _parse_tool_arguments(function.get("arguments")),
                "id": call_id,
                "type": "tool_call",
            }
        )
    return parsed


def _parse_tool_arguments(raw_arguments: object) -> dict[str, object]:
    """Decode function.arguments JSON to an object; never include the raw text."""
    if not isinstance(raw_arguments, str):
        raise ModelProviderError("invalid_response", type(raw_arguments).__name__)
    try:
        decoded = json.loads(raw_arguments)
    except json.JSONDecodeError:
        raise ModelProviderError("invalid_response", "JSONDecodeError") from None
    if not isinstance(decoded, dict):
        raise ModelProviderError("invalid_response", type(decoded).__name__)
    return decoded


def _ai_chunk_from_payload(payload: object) -> AIMessageChunk:
    """Normalize one SSE data payload without retaining provider JSON."""
    if not isinstance(payload, dict):
        raise ModelProviderError("invalid_response", type(payload).__name__)
    usage = _usage_metadata(payload.get("usage"))
    choices = payload.get("choices")
    if choices == [] and usage is not None:
        return AIMessageChunk(content="", usage_metadata=usage)
    if not isinstance(choices, list) or not choices:
        raise ModelProviderError("invalid_response", type(choices).__name__)
    first = choices[0]
    if not isinstance(first, dict):
        raise ModelProviderError("invalid_response", type(first).__name__)
    delta = first.get("delta")
    if not isinstance(delta, dict):
        raise ModelProviderError("invalid_response", type(delta).__name__)
    raw_content = delta.get("content")
    if raw_content is None:
        content = ""
    elif isinstance(raw_content, str):
        content = raw_content
    else:
        raise ModelProviderError("invalid_response", type(raw_content).__name__)
    return AIMessageChunk(
        content=content,
        tool_call_chunks=_parse_tool_call_chunks(delta.get("tool_calls")),
        usage_metadata=usage,
    )


def _parse_tool_call_chunks(raw_calls: object) -> list[ToolCallChunk]:
    if raw_calls is None:
        return []
    if not isinstance(raw_calls, list):
        raise ModelProviderError("invalid_response", type(raw_calls).__name__)
    chunks: list[ToolCallChunk] = []
    for item in raw_calls:
        if not isinstance(item, dict):
            raise ModelProviderError("invalid_response", type(item).__name__)
        index = item.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise ModelProviderError("invalid_response", type(index).__name__)
        call_id = item.get("id")
        if call_id is not None and not isinstance(call_id, str):
            raise ModelProviderError("invalid_response", type(call_id).__name__)
        function = item.get("function")
        if not isinstance(function, dict):
            raise ModelProviderError("invalid_response", type(function).__name__)
        name = function.get("name")
        arguments = function.get("arguments")
        if name is not None and not isinstance(name, str):
            raise ModelProviderError("invalid_response", type(name).__name__)
        if arguments is not None and not isinstance(arguments, str):
            raise ModelProviderError("invalid_response", type(arguments).__name__)
        chunks.append(
            ToolCallChunk(
                name=name,
                args=arguments or "",
                id=call_id,
                index=index,
                type="tool_call_chunk",
            )
        )
    return chunks


def _usage_metadata(raw_usage: object) -> UsageMetadata | None:
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, Mapping):
        raise ModelProviderError("invalid_response", type(raw_usage).__name__)
    prompt = raw_usage.get("prompt_tokens")
    completion = raw_usage.get("completion_tokens")
    total = raw_usage.get("total_tokens")
    for value in (prompt, completion, total):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ModelProviderError("invalid_response", type(value).__name__)
    return cast(
        UsageMetadata,
        {"input_tokens": prompt, "output_tokens": completion, "total_tokens": total},
    )
