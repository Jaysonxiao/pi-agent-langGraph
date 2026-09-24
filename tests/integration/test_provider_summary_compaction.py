"""M8.9-R2-F provider-backed summary and compaction contracts."""

import asyncio
from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeCancelledError

from pi_agent.context import AsyncModelSummarizer, ContextConfig
from pi_agent.domain import create_initial_state
from pi_agent.domain.state import AgentTurnInput
from pi_agent.graph import AsyncRunContext, build_async_minimal_graph
from pi_agent.models import CompatibleAsyncChatModel


class ScriptedProviderClient:
    def __init__(
        self,
        replies: Sequence[AIMessage] = (),
        *,
        error: BaseException | None = None,
    ) -> None:
        self._replies = list(replies)
        self._error = error
        self.calls: list[tuple[AnyMessage, ...]] = []

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> object:
        del config
        self.calls.append(tuple(messages))
        if self._error is not None:
            raise self._error
        return self._replies.pop(0)

    async def aclose(self) -> None:
        return None


def _history() -> AgentTurnInput:
    state = create_initial_state("recent", message_id="recent-1")
    state["messages"] = [
        HumanMessage(content="old private input", id="old-1"),
        AIMessage(content="old answer", id="old-2"),
        HumanMessage(content="recent", id="recent-1"),
    ]
    return state


def test_provider_summary_is_ephemeral_and_main_model_receives_compaction() -> None:
    summary_client = ScriptedProviderClient((AIMessage(content="Earlier goal retained."),))
    main_client = ScriptedProviderClient((AIMessage(content="done", id="main-1"),))
    summary_model = CompatibleAsyncChatModel(summary_client)
    main_model = CompatibleAsyncChatModel(main_client)

    result = asyncio.run(
        build_async_minimal_graph().ainvoke(
            _history(),
            context=AsyncRunContext(
                model=main_model,
                context_config=ContextConfig(
                    compaction_threshold_tokens=1,
                    async_summarizer=AsyncModelSummarizer(summary_model),
                ),
            ),
        )
    )

    assert len(summary_client.calls) == 1
    assert len(main_client.calls) == 1
    assert main_client.calls[0] == (
        SystemMessage(content="Earlier goal retained."),
        HumanMessage(content="recent", id="recent-1"),
    )
    assert result["messages"][:3] == _history()["messages"]
    assert not any(isinstance(message, SystemMessage) for message in result["messages"])
    assert result["status"] == "completed"


def test_provider_summary_failure_stops_main_model_and_sanitizes_state() -> None:
    summary_model = CompatibleAsyncChatModel(
        ScriptedProviderClient(error=RuntimeError("Bearer synthetic-secret and original body"))
    )
    main_client = ScriptedProviderClient((AIMessage(content="must not run"),))

    result = asyncio.run(
        build_async_minimal_graph().ainvoke(
            _history(),
            context=AsyncRunContext(
                model=CompatibleAsyncChatModel(main_client),
                context_config=ContextConfig(
                    compaction_threshold_tokens=1,
                    async_summarizer=AsyncModelSummarizer(summary_model),
                ),
            ),
        )
    )

    assert main_client.calls == []
    assert result["status"] == "failed"
    assert result["error"] is not None
    assert result["error"]["code"] == "context_error"
    assert "synthetic-secret" not in str(result)
    assert "original body" not in str(result)


def test_provider_summary_cancellation_propagates_without_main_call() -> None:
    summary_model = CompatibleAsyncChatModel(ScriptedProviderClient(error=asyncio.CancelledError()))
    main_client = ScriptedProviderClient((AIMessage(content="must not run"),))

    async def scenario() -> None:
        with pytest.raises(NodeCancelledError) as raised:
            await build_async_minimal_graph().ainvoke(
                _history(),
                context=AsyncRunContext(
                    model=CompatibleAsyncChatModel(main_client),
                    context_config=ContextConfig(
                        compaction_threshold_tokens=1,
                        async_summarizer=AsyncModelSummarizer(summary_model),
                    ),
                ),
            )
        assert isinstance(raised.value.__cause__, asyncio.CancelledError)

    asyncio.run(scenario())
    assert main_client.calls == []
