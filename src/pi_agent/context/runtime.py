"""Prepare and diagnose model input without changing durable conversation state."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage

from pi_agent.context.assembly import assemble_context_messages
from pi_agent.context.compaction import plan_context_compaction
from pi_agent.context.instructions import (
    WorkspaceInstruction,
    discover_workspace_instruction_files,
    load_workspace_instructions,
)
from pi_agent.context.messages import context_bytes, estimate_tokens, safe_boundaries
from pi_agent.context.summarizer import Summarizer, preserve_tool_facts
from pi_agent.context.summary import apply_compaction_summary
from pi_agent.security import WorkspacePathPolicy


class ContextPreparationError(ValueError):
    """Context cannot be prepared without losing required information."""


@dataclass(frozen=True, slots=True)
class ContextConfig:
    """Dependencies and limits for one run; none are checkpoint state."""

    workspace_policy: WorkspacePathPolicy | None = None
    active_path: str | None = None
    max_bytes: int | None = None
    keep_recent_messages: int | None = None
    summary: str | None = None
    global_instruction_file: Path | None = None
    prompt_template: str = "{instructions}"
    max_tokens: int | None = None
    compaction_threshold_tokens: int | None = None
    keep_recent_turns: int = 1
    summarizer: Summarizer | None = None

    def __post_init__(self) -> None:
        if (self.workspace_policy is None) != (self.active_path is None):
            raise ValueError("workspace_policy and active_path must be supplied together.")
        for name in (
            "max_bytes",
            "max_tokens",
            "compaction_threshold_tokens",
            "keep_recent_messages",
            "keep_recent_turns",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer.")
        if self.summary is not None and self.keep_recent_messages is None:
            raise ValueError("keep_recent_messages is required when summary is supplied.")
        if self.summary is not None and self.summarizer is not None:
            raise ValueError("Choose summary or summarizer, not both.")
        if self.compaction_threshold_tokens is not None and self.summarizer is None:
            raise ValueError("compaction_threshold_tokens requires a summarizer.")
        if self.prompt_template.count("{instructions}") != 1:
            raise ValueError("prompt_template must contain exactly one {instructions} placeholder.")


@dataclass(frozen=True, slots=True)
class PreparedContext:
    messages: tuple[AnyMessage, ...]
    instruction_sources: tuple[str, ...]
    original_bytes: int
    prepared_bytes: int
    original_tokens: int
    prepared_tokens: int
    removed_messages: int
    summary_applied: bool

    def diagnostic(self) -> dict[str, object]:
        """Content-free snapshot; CLI does not echo prompts or credentials."""
        return {
            "instruction_sources": self.instruction_sources,
            "message_roles": [message.type for message in self.messages],
            "original_bytes": self.original_bytes,
            "prepared_bytes": self.prepared_bytes,
            "estimated_original_tokens": self.original_tokens,
            "estimated_prepared_tokens": self.prepared_tokens,
            "token_estimator": "ceil(UTF-8 content/tool bytes / 4) + 4 per message",
            "removed_messages": self.removed_messages,
            "summary_applied": self.summary_applied,
        }


def _instructions(config: ContextConfig) -> tuple[WorkspaceInstruction, ...]:
    instructions: tuple[WorkspaceInstruction, ...] = ()
    if config.global_instruction_file is not None:
        # Explicit caller configuration only; no implicit home-directory scan.
        path = config.global_instruction_file.absolute()
        policy = WorkspacePathPolicy(path.parent)
        instructions = load_workspace_instructions(policy, (path,))
    if config.workspace_policy is not None and config.active_path is not None:
        paths = discover_workspace_instruction_files(config.workspace_policy, config.active_path)
        seen = {instruction.path for instruction in instructions}
        instructions += load_workspace_instructions(
            config.workspace_policy, tuple(path for path in paths if path not in seen)
        )
    return instructions


def _fits(messages: Sequence[AnyMessage], config: ContextConfig) -> bool:
    return (config.max_bytes is None or context_bytes(messages) <= config.max_bytes) and (
        config.max_tokens is None or estimate_tokens(messages) <= config.max_tokens
    )


def inspect_model_context(messages: Sequence[AnyMessage], config: ContextConfig) -> PreparedContext:
    """Assemble -> plan on FULL history -> summarize -> enforce final limits.

    Required system messages and recent user turns are never silently dropped.
    Any failure leaves the original history intact and stops the main model.
    """
    instructions = _instructions(config)
    assembled = assemble_context_messages(messages, instructions)
    rule_text = str(assembled[0].content) if instructions else ""
    rendered = config.prompt_template.replace("{instructions}", rule_text)
    history = (*messages,)
    assembled = (SystemMessage(rendered), *history) if rendered else history
    safe_boundaries(assembled)

    leading = 0
    while leading < len(assembled) and isinstance(assembled[leading], SystemMessage):
        leading += 1
    rest = assembled[leading:]
    # The latest N human turns are protected even when a tool batch ends the input.
    turns = [index for index, message in enumerate(rest) if isinstance(message, HumanMessage)]
    turn_start = turns[max(0, len(turns) - config.keep_recent_turns)] if turns else 0
    keep = max(len(rest) - turn_start, config.keep_recent_messages or 1)
    plan = plan_context_compaction(assembled, keep)
    prepared = assembled
    summarized = False
    removed = 0
    threshold = config.compaction_threshold_tokens
    triggered = not _fits(assembled, config) or (
        threshold is not None and estimate_tokens(assembled) > threshold
    )
    if plan.removable and (config.summary is not None or (config.summarizer and triggered)):
        if config.summary is not None:
            summary = config.summary
        else:
            assert config.summarizer is not None
            # Protect shared message objects even from a badly behaved adapter.
            summary = config.summarizer.summarize(
                tuple(message.model_copy(deep=True) for message in plan.removable)
            )
        if not isinstance(summary, str) or not summary.strip():
            raise ContextPreparationError("Summary must be nonblank text.")
        summary = preserve_tool_facts(plan.removable, summary)
        prepared = apply_compaction_summary(plan, summary)
        summarized = True
        removed = len(plan.removable)

    if not _fits(prepared, config) and not summarized and config.summarizer is None:
        # Budget-only mode may remove old complete turns, never part of the latest turn.
        candidates = [index for index in turns if 0 < index <= len(plan.removable)]
        for start in candidates:
            facts = preserve_tool_facts(rest[:start], "")
            fact_messages = (SystemMessage(facts),) if facts else ()
            candidate = (*plan.leading_system, *fact_messages, *rest[start:])
            safe_boundaries(candidate)
            if _fits(candidate, config):
                prepared, removed = candidate, start
                break
    if not _fits(prepared, config):
        raise ContextPreparationError(
            "Required rules, summary and recent turns exceed context budget."
        )
    safe_boundaries(prepared)
    return PreparedContext(
        messages=prepared,
        instruction_sources=tuple(instruction.path.as_posix() for instruction in instructions),
        original_bytes=context_bytes(assembled),
        prepared_bytes=context_bytes(prepared),
        original_tokens=estimate_tokens(assembled),
        prepared_tokens=estimate_tokens(prepared),
        removed_messages=removed,
        summary_applied=summarized,
    )


def prepare_model_messages(
    messages: Sequence[AnyMessage], config: ContextConfig
) -> tuple[AnyMessage, ...]:
    return inspect_model_context(messages, config).messages
