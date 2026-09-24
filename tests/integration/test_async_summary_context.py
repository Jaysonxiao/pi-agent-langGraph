"""Red graph-level tests for the learner-owned M8.5-R3 context integration."""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.context import AsyncModelSummarizer, ContextConfig
from pi_agent.domain import create_initial_state
from pi_agent.domain.state import AgentTurnInput
from pi_agent.graph import AsyncRunContext, build_async_minimal_graph
from pi_agent.models import AsyncFakeChatModel


def _history() -> AgentTurnInput:
    state = create_initial_state("recent", message_id="recent-1")
    state["messages"] = [
        HumanMessage(content="old goal", id="old-1"),
        AIMessage(content="old answer", id="old-2"),
        HumanMessage(content="recent", id="recent-1"),
    ]
    return state


def test_async_summary_is_ephemeral_and_precedes_main_model() -> None:
    summary_model = AsyncFakeChatModel(AIMessage(content="Earlier goal: old goal."))
    main_model = AsyncFakeChatModel(AIMessage(content="done", id="main-1"))
    config = RunnableConfig(tags=["m85-r3"])

    result = asyncio.run(
        build_async_minimal_graph().ainvoke(
            _history(),
            config=config,
            context=AsyncRunContext(
                model=main_model,
                context_config=ContextConfig(
                    compaction_threshold_tokens=1,
                    async_summarizer=AsyncModelSummarizer(summary_model),
                ),
            ),
        )
    )

    assert summary_model.configs[0] is not None
    assert "m85-r3" in summary_model.configs[0].get("tags", [])
    assert len(main_model.calls) == 1
    assert isinstance(main_model.calls[0][0], SystemMessage)
    assert main_model.calls[0][0].content == "Earlier goal: old goal."
    assert main_model.calls[0][1] == HumanMessage(content="recent", id="recent-1")
    assert result["messages"][:3] == _history()["messages"]
    assert not any(isinstance(message, SystemMessage) for message in result["messages"])


def test_async_summary_failure_stops_main_model_and_preserves_history() -> None:
    summary_model = AsyncFakeChatModel(error=RuntimeError("Authorization: Bearer synthetic-secret"))
    main_model = AsyncFakeChatModel(AIMessage(content="must not run"))

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

    assert main_model.calls == []
    assert len(summary_model.calls) == 1
    assert result["messages"] == _history()["messages"]
    assert result["status"] == "failed"
    assert result["error"] is not None and result["error"]["code"] == "context_error"
    assert "synthetic-secret" not in str(result)
