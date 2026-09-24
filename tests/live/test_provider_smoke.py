"""M8.9-R2-A live contract for one compatible async provider reply.

The module is opt-in.  It must never contact a provider during the default
offline suite; set ``PI_AGENT_LIVE=1`` and load ``.env`` explicitly with uv
when the learner is ready to run it.
"""

import asyncio
import os
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.cli.provider import ProviderCliOptions
from pi_agent.cli.runtime import run_provider_session
from pi_agent.context import AsyncModelSummarizer, ContextConfig
from pi_agent.domain import create_initial_state
from pi_agent.graph import AsyncRunContext, build_async_minimal_graph
from pi_agent.models import CompatibleAsyncChatModel, UsageLedger, collect_async_response
from pi_agent.models.async_base import AsyncChatModel
from pi_agent.models.config import ModelConfig, ModelOptions, resolve_model_config
from pi_agent.models.http_client import build_async_provider_client

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("PI_AGENT_LIVE") != "1",
        reason="live provider smoke requires PI_AGENT_LIVE=1",
    ),
]


def _live_config() -> ModelConfig:
    config = resolve_model_config(ModelOptions(), dict(os.environ))
    assert config.provider == "compatible"
    return config


class RecordingAsyncModel:
    def __init__(self, delegate: AsyncChatModel) -> None:
        self.delegate = delegate
        self.calls: list[tuple[AnyMessage, ...]] = []

    async def ainvoke(
        self,
        messages: Sequence[AnyMessage],
        config: RunnableConfig | None = None,
        /,
    ) -> AIMessage:
        self.calls.append(tuple(messages))
        return await self.delegate.ainvoke(messages, config)


def test_live_compatible_provider_returns_one_reply() -> None:
    """Exercise the learner-owned client factory without printing secrets."""

    async def scenario() -> None:
        client = build_async_provider_client(_live_config())
        model = CompatibleAsyncChatModel(client)
        try:
            response = await model.ainvoke(
                (HumanMessage(content="Reply with exactly LIVE_SMOKE_OK"),)
            )
            assert isinstance(response.content, str)
            assert "LIVE_SMOKE_OK" in response.content
        finally:
            await model.aclose()

    asyncio.run(scenario())


def test_live_compatible_provider_streams_one_reply() -> None:
    async def scenario() -> None:
        client = build_async_provider_client(_live_config())
        model = CompatibleAsyncChatModel(client)
        try:
            response = await collect_async_response(
                model.astream((HumanMessage(content="Reply with exactly STREAM_SMOKE_OK"),)),
                "live-stream",
                UsageLedger(),
            )
            assert isinstance(response.content, str)
            assert "STREAM_SMOKE_OK" in response.content
        finally:
            await model.aclose()

    asyncio.run(scenario())


def test_live_provider_session_resumes_after_sqlite_reopen(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = build_async_provider_client(_live_config())
        owned = CompatibleAsyncChatModel(client)
        model = RecordingAsyncModel(owned)
        options = ProviderCliOptions(
            provider="compatible",
            prompt="Reply with exactly RESUME_FIRST_OK",
            events="jsonl",
            database=tmp_path / "live-resume.sqlite",
            session_id="live-resume",
            workspace=tmp_path,
        )
        try:
            await run_provider_session(options, model=model, message_id="live-user-1")
            await run_provider_session(
                replace(options, prompt="Reply with exactly RESUME_SECOND_OK"),
                model=model,
                message_id="live-user-2",
            )
        finally:
            await owned.aclose()

        assert len(model.calls) == 2
        assert [message.type for message in model.calls[1]] == ["human", "ai", "human"]

    asyncio.run(scenario())


def test_live_provider_summary_and_compaction_path() -> None:
    async def scenario() -> None:
        client = build_async_provider_client(_live_config())
        owned = CompatibleAsyncChatModel(client)
        summary_model = RecordingAsyncModel(owned)
        main_model = RecordingAsyncModel(owned)
        state = create_initial_state("recent question", message_id="live-recent")
        state["messages"] = [
            HumanMessage(content="old synthetic goal", id="live-old-user"),
            AIMessage(content="old synthetic answer", id="live-old-ai"),
            HumanMessage(content="recent question", id="live-recent"),
        ]
        try:
            result = await build_async_minimal_graph().ainvoke(
                state,
                context=AsyncRunContext(
                    model=main_model,
                    context_config=ContextConfig(
                        compaction_threshold_tokens=1,
                        async_summarizer=AsyncModelSummarizer(summary_model),
                    ),
                ),
            )
        finally:
            await owned.aclose()

        assert result["status"] == "completed"
        assert len(summary_model.calls) == 1
        assert len(main_model.calls) == 1
        assert isinstance(main_model.calls[0][0], SystemMessage)
        assert result["messages"][:3] == state["messages"]

    asyncio.run(scenario())
