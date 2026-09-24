"""Red tests for the learner-owned M8.5-R1 async model node."""

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import NodeCancelledError

from pi_agent.context import ContextConfig
from pi_agent.domain import create_initial_state
from pi_agent.graph import AsyncRunContext, build_async_minimal_graph
from pi_agent.models import AsyncFakeChatModel
from pi_agent.security import WorkspacePathPolicy


def test_async_graph_prepares_context_and_preserves_durable_history(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use async project rules.", encoding="utf-8")
    active = tmp_path / "src" / "main.py"
    active.parent.mkdir()
    active.write_text("print('ok')", encoding="utf-8")
    model = AsyncFakeChatModel(AIMessage(content="done", id="assistant-async"))
    config = RunnableConfig(tags=["m85-r1"])

    result = asyncio.run(
        build_async_minimal_graph().ainvoke(
            create_initial_state("hello", message_id="input-1"),
            config=config,
            context=AsyncRunContext(
                model=model,
                context_config=ContextConfig(
                    workspace_policy=WorkspacePathPolicy(tmp_path),
                    active_path=str(active),
                ),
            ),
        )
    )

    assert isinstance(model.calls[0][0], SystemMessage)
    assert "Use async project rules." in model.calls[0][0].content
    assert model.configs[0] is not None
    assert "m85-r1" in model.configs[0].get("tags", [])
    assert result["messages"] == [
        HumanMessage(content="hello", id="input-1"),
        AIMessage(content="done", id="assistant-async"),
    ]
    assert result["status"] == "completed"


def test_async_graph_model_failure_is_safe_and_preserves_history() -> None:
    model = AsyncFakeChatModel(error=RuntimeError("Authorization: Bearer synthetic-secret"))

    result = asyncio.run(
        build_async_minimal_graph().ainvoke(
            create_initial_state("hello", message_id="input-1"),
            context=AsyncRunContext(model=model),
        )
    )

    assert result["messages"] == [HumanMessage(content="hello", id="input-1")]
    assert result["status"] == "failed"
    assert result["error"] == {
        "code": "model_error",
        "exception_type": "RuntimeError",
        "message": "Model request failed.",
    }
    assert "synthetic-secret" not in str(result)


def test_async_graph_propagates_cancellation() -> None:
    model = AsyncFakeChatModel(error=asyncio.CancelledError())

    with pytest.raises(NodeCancelledError) as caught:
        asyncio.run(
            build_async_minimal_graph().ainvoke(
                create_initial_state("hello"),
                context=AsyncRunContext(model=model),
            )
        )

    assert isinstance(caught.value.__cause__, asyncio.CancelledError)
