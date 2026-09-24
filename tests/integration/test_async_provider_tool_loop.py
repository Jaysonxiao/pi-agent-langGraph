"""R2-C red test for the async provider-to-read-only-tool loop."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import cast

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.domain.state import create_initial_state
from pi_agent.graph.async_context import AsyncRunContext
from pi_agent.graph.builder import build_async_tool_graph
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.runtime.cancellation import AsyncCancellationToken
from pi_agent.tools.async_registry import AsyncToolRegistry


class ScriptedAsyncModel:
    def __init__(self, responses: Sequence[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[AnyMessage, ...]] = []

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        del config
        self.calls.append(tuple(messages))
        return self._responses.pop(0)


class ReadTool:
    name = "read"

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, raw_args: Mapping[str, object]) -> str:
        self.calls += 1
        assert raw_args == {"path": "README.md"}
        return "README content"


def test_async_provider_tool_loop_executes_read_and_replies() -> None:
    read_tool = ReadTool()
    model: AsyncChatModel = ScriptedAsyncModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read",
                        "args": {"path": "README.md"},
                        "id": "call-read-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="README loaded", id="assistant-final"),
        ]
    )
    context = AsyncRunContext(
        model=model,
        tools=AsyncToolRegistry([read_tool]),
        cancellation_token=AsyncCancellationToken(),
        max_tool_rounds=2,
    )

    result = asyncio.run(
        build_async_tool_graph().ainvoke(
            create_initial_state("read README.md"),
            context=context,
        )
    )

    assert result["status"] == "completed"
    assert result["messages"][-1].content == "README loaded"
    assert result["messages"][2].tool_call_id == "call-read-1"


def test_async_provider_tool_loop_projects_unknown_tool_without_execution() -> None:
    model: AsyncChatModel = ScriptedAsyncModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "delete", "args": {}, "id": "call-unknown", "type": "tool_call"}
                ],
            ),
            AIMessage(content="handled", id="assistant-final"),
        ]
    )
    context = AsyncRunContext(
        model=model,
        tools=AsyncToolRegistry(),
        cancellation_token=AsyncCancellationToken(),
    )

    result = asyncio.run(
        build_async_tool_graph().ainvoke(create_initial_state("delete README.md"), context=context)
    )

    tool_message = result["messages"][2]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == "call-unknown"
    assert isinstance(tool_message.content, str)
    assert cast(dict[str, object], json.loads(tool_message.content))["code"] == "unknown_tool"
    assert result["status"] == "completed"


def test_async_provider_tool_loop_stops_at_round_limit() -> None:
    read_tool = ReadTool()
    model: AsyncChatModel = ScriptedAsyncModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read",
                        "args": {"path": "README.md"},
                        "id": "call-limited",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )
    context = AsyncRunContext(
        model=model,
        tools=AsyncToolRegistry([read_tool]),
        cancellation_token=AsyncCancellationToken(),
        max_tool_rounds=0,
    )

    result = asyncio.run(
        build_async_tool_graph().ainvoke(create_initial_state("read README.md"), context=context)
    )

    tool_message = result["messages"][2]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == "call-limited"
    assert isinstance(tool_message.content, str)
    assert cast(dict[str, object], json.loads(tool_message.content))["code"] == "tool_round_limit"
    assert result["status"] == "failed"
    assert read_tool.calls == 0
