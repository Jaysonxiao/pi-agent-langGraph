"""Provider client adapter for the M8.5 native async model port."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol, runtime_checkable

from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.models.errors import ModelProviderError


class AsyncProviderClient(Protocol):
    """Small async SDK subset isolated behind the project model boundary."""

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        """Return one provider response without leaking SDK types into graph code."""
        ...

    async def aclose(self) -> None:
        """Release any client-owned async resources."""
        ...


@runtime_checkable
class AsyncStreamingProviderClient(Protocol):
    """Optional provider capability for native response streaming."""

    def astream(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AsyncIterator[AIMessageChunk]:
        """Yield normalized provider chunks and own the response lifecycle."""
        ...

    async def aclose(self) -> None:
        """Release any client-owned async resources."""
        ...


class CompatibleAsyncChatModel:
    """Normalize one compatible async provider client to AsyncChatModel."""

    def __init__(self, client: AsyncProviderClient) -> None:
        self._client = client

    @property
    def supports_tool_binding(self) -> bool:
        return callable(getattr(self._client, "bind_tools", None))

    @property
    def supports_streaming(self) -> bool:
        return isinstance(self._client, AsyncStreamingProviderClient)

    def bind_tools(self, tools: Sequence[Mapping[str, object]]) -> CompatibleAsyncChatModel:
        """Bind only clients that can transmit tool schemas to the provider."""
        binder = getattr(self._client, "bind_tools", None)
        if not callable(binder):
            raise ModelProviderError("client_creation_failed", "ToolBindingUnsupported")
        binder(tools)
        return self

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        """Call the provider once and return a complete safe AIMessage."""
        try:
            # messages/config 原样交给客户端, 适配器不改写 durable 或 runnable 配置.
            response = await self._client.ainvoke(messages, config)
        except asyncio.CancelledError:
            raise
        except ModelProviderError:
            raise
        except Exception as exc:
            # 丢弃异常链和正文, 只保留稳定错误码与异常类型名.
            raise ModelProviderError("provider_call_failed", type(exc).__name__) from None
        if not isinstance(response, AIMessage):
            raise ModelProviderError("invalid_response", type(response).__name__)
        return response

    async def astream(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AsyncIterator[AIMessageChunk]:
        """Forward a native stream while keeping provider failures sanitized."""
        if not isinstance(self._client, AsyncStreamingProviderClient):
            raise ModelProviderError("provider_call_failed", "StreamingNotSupported")
        chunks = self._client.astream(messages, config)
        try:
            async for chunk in chunks:
                if not isinstance(chunk, AIMessageChunk):
                    raise ModelProviderError("invalid_response", type(chunk).__name__)
                yield chunk
        except asyncio.CancelledError:
            raise
        except ModelProviderError:
            raise
        except Exception as exc:
            raise ModelProviderError("provider_call_failed", type(exc).__name__) from None
        finally:
            close = getattr(chunks, "aclose", None)
            if callable(close):
                await close()

    async def aclose(self) -> None:
        """Close the owned async client at the runtime boundary."""
        await self._client.aclose()
