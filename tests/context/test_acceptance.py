"""M7 combined boundaries that independent component tests cannot establish."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from pi_agent.context import (
    ContextConfig,
    ContextPreparationError,
    ModelSummarizer,
    fit_context_messages,
    inspect_model_context,
    plan_context_compaction,
    prepare_model_messages,
)
from pi_agent.context.messages import context_bytes, estimate_tokens
from pi_agent.models.fake import FakeChatModel, ScriptedChatModel
from pi_agent.security import WorkspacePathPolicy


def test_global_ancestor_current_and_template_order(tmp_path: Path) -> None:
    global_file = tmp_path / "global.md"
    global_file.write_text("GLOBAL", encoding="utf-8")
    workspace = tmp_path / "workspace"
    leaf = workspace / "pkg"
    leaf.mkdir(parents=True)
    (workspace / "AGENTS.md").write_text("ROOT", encoding="utf-8")
    (leaf / "AGENTS.md").write_text("LEAF", encoding="utf-8")
    prepared = inspect_model_context(
        (HumanMessage("hello"),),
        ContextConfig(
            workspace_policy=WorkspacePathPolicy(workspace),
            active_path="pkg",
            global_instruction_file=global_file,
            prompt_template="BASE\n{instructions}\nEND",
        ),
    )
    content = prepared.messages[0].content
    assert isinstance(content, str)
    assert content.index("BASE") < content.index("GLOBAL") < content.index("ROOT")
    assert content.index("ROOT") < content.index("LEAF") < content.index("END")
    assert len(prepared.instruction_sources) == 3


def test_summarizer_receives_full_old_history_before_budget_and_result_is_checked() -> None:
    model = FakeChatModel("short")
    history = (HumanMessage("old" * 200), AIMessage("answer" * 50), HumanMessage("new"))
    before = [message.model_dump() for message in history]
    result = inspect_model_context(
        history,
        ContextConfig(
            max_bytes=20,
            summarizer=ModelSummarizer(model),
            keep_recent_messages=1,
        ),
    )
    payload = model.calls[0][1].content
    assert isinstance(payload, str) and "old" * 200 in payload and "answer" * 50 in payload
    assert result.summary_applied and result.removed_messages == 2
    assert result.prepared_bytes <= 20
    assert result.messages[-1] is history[-1]
    assert [message.model_dump() for message in history] == before


@pytest.mark.parametrize("reply", [" ", "X" * 100])
def test_blank_or_oversized_summary_fails_without_silently_removing_recent_turn(reply: str) -> None:
    model = FakeChatModel(reply)
    history = (HumanMessage("old" * 100), HumanMessage("latest"))
    with pytest.raises((ContextPreparationError, ValueError)):
        prepare_model_messages(
            history, ContextConfig(max_bytes=20, summarizer=ModelSummarizer(model))
        )
    assert history[-1].content == "latest"


def test_threshold_and_token_budget_are_independent_of_bytes() -> None:
    history = (HumanMessage("old" * 100), HumanMessage("new"))
    model = FakeChatModel("s")
    # Equality does not trigger compaction.
    prepare_model_messages(
        history,
        ContextConfig(
            summarizer=ModelSummarizer(model),
            compaction_threshold_tokens=estimate_tokens(history),
        ),
    )
    assert model.calls == []
    result = inspect_model_context(
        history,
        ContextConfig(
            summarizer=ModelSummarizer(model),
            max_tokens=12,
        ),
    )
    assert result.summary_applied and result.prepared_tokens <= 12


def test_budget_preserves_latest_complete_turn_and_can_drop_an_old_turn() -> None:
    latest = (HumanMessage("new"), AIMessage("reply"))
    messages = (HumanMessage("OLD" * 100), AIMessage("old reply"), *latest)
    result = prepare_model_messages(messages, ContextConfig(max_bytes=8))
    assert result == latest
    with pytest.raises(ContextPreparationError):
        prepare_model_messages(messages, ContextConfig(max_bytes=5))


def test_system_rules_alone_exceeding_budget_stop_preparation() -> None:
    with pytest.raises(ContextPreparationError):
        prepare_model_messages(
            (SystemMessage("rules" * 100), HumanMessage("hi")), ContextConfig(max_bytes=10)
        )


def test_parallel_tool_batch_is_atomic_in_planner_and_budget() -> None:
    call = AIMessage(
        "",
        tool_calls=[
            {"id": "a", "name": "edit_file", "args": {"path": "x.py"}},
            {"id": "b", "name": "read_file", "args": {"path": "y.py"}},
        ],
    )
    # Results may arrive in a different order than calls.
    batch = (call, ToolMessage("b", tool_call_id="b"), ToolMessage("a", tool_call_id="a"))
    history = (HumanMessage("edit"), *batch)
    assert plan_context_compaction(history, 1).recent == batch
    assert fit_context_messages(history, context_bytes(batch) - 1).messages == ()
    assert fit_context_messages(history, context_bytes(batch)).messages == batch
    assert context_bytes(batch) > sum(len(str(message.content)) for message in batch)


def test_unknown_tool_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="pending"):
        prepare_model_messages((ToolMessage("bad", tool_call_id="unknown"),), ContextConfig())


def test_summary_keeps_file_mutation_facts_even_when_model_omits_them() -> None:
    history = (
        HumanMessage("edit"),
        AIMessage("", tool_calls=[{"id": "a", "name": "edit_file", "args": {"path": "x.py"}}]),
        ToolMessage('{"path":"x.py","applied":true}', tool_call_id="a", status="success"),
        AIMessage("done"),
        HumanMessage("what changed?"),
    )
    result = prepare_model_messages(
        history,
        ContextConfig(
            compaction_threshold_tokens=1,
            summarizer=ModelSummarizer(FakeChatModel("summary")),
        ),
    )
    assert "x.py" in str(result[0].content)
    assert "applied" in str(result[0].content)
    assert "success" in str(result[0].content)
    assert result[-1] is history[-1]


def test_mutating_summarizer_cannot_change_original_history() -> None:
    class Mutator:
        def summarize(self, messages: Sequence[AnyMessage], /) -> str:
            messages[0].content = "mutated"
            raise RuntimeError("broken adapter")

    original = HumanMessage("old")
    with pytest.raises(RuntimeError):
        prepare_model_messages(
            (original, HumanMessage("new")),
            ContextConfig(
                summarizer=Mutator(),
                compaction_threshold_tokens=1,
            ),
        )
    assert original.content == "old"


def test_summary_adapter_rejects_tool_request() -> None:
    model = ScriptedChatModel(
        [
            AIMessage(
                "",
                tool_calls=[
                    {"name": "edit", "id": "a", "args": {}},
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="without tool calls"):
        ModelSummarizer(model).summarize((HumanMessage("old"),))


def test_budget_only_retains_old_file_operation_facts() -> None:
    history = (
        HumanMessage("old " * 1000),
        AIMessage("", tool_calls=[{"id": "a", "name": "edit", "args": {"path": "x.py"}}]),
        ToolMessage("applied", tool_call_id="a"),
        HumanMessage("latest"),
    )
    result = inspect_model_context(history, ContextConfig(max_bytes=500))
    assert result.prepared_bytes <= 500
    assert "x.py" in str(result.messages[0].content)
    assert "applied" in str(result.messages[0].content)
    assert result.messages[-1] is history[-1]


def test_keep_recent_turns_retains_entire_conversations() -> None:
    messages = (
        HumanMessage("first"),
        AIMessage("one"),
        HumanMessage("second"),
        AIMessage("two"),
        HumanMessage("third"),
    )
    prepared = prepare_model_messages(
        messages,
        ContextConfig(
            summary="earlier",
            keep_recent_messages=1,
            keep_recent_turns=2,
        ),
    )
    assert prepared[1:] == messages[2:]


@pytest.mark.parametrize(
    "config",
    [
        {"max_bytes": 0},
        {"max_tokens": -1},
        {"keep_recent_turns": 0},
        {"compaction_threshold_tokens": 1},
        {"active_path": "."},
        {"prompt_template": "missing placeholder"},
    ],
)
def test_invalid_configuration_is_rejected(config: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ContextConfig(**config)  # type: ignore[arg-type]
