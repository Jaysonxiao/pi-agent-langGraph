"""Asynchronous context preparation entry point for M8.5-R3."""

from collections.abc import Sequence

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from pi_agent.context.assembly import assemble_context_messages
from pi_agent.context.compaction import plan_context_compaction
from pi_agent.context.messages import estimate_tokens, safe_boundaries
from pi_agent.context.runtime import (
    ContextConfig,
    ContextPreparationError,
    _fits,
    _instructions,
    prepare_model_messages,
)
from pi_agent.context.summarizer import preserve_tool_facts
from pi_agent.context.summary import apply_compaction_summary


async def prepare_model_messages_async(
    messages: Sequence[AnyMessage],
    config: ContextConfig,
    run_config: RunnableConfig | None = None,
    /,
) -> tuple[AnyMessage, ...]:
    """Prepare ephemeral model context and await an optional async summary."""
    # 没有异步摘要器时完全复用同步路径, 保持既有装配/预算语义.
    if config.async_summarizer is None:
        return prepare_model_messages(messages, config)
    return await _prepare_with_async_summary(messages, config, run_config)


async def _prepare_with_async_summary(
    messages: Sequence[AnyMessage],
    config: ContextConfig,
    run_config: RunnableConfig | None,
) -> tuple[AnyMessage, ...]:
    """Mirror inspect_model_context, awaiting the async summarizer when triggered."""
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
    turns = [index for index, message in enumerate(rest) if isinstance(message, HumanMessage)]
    turn_start = turns[max(0, len(turns) - config.keep_recent_turns)] if turns else 0
    keep = max(len(rest) - turn_start, config.keep_recent_messages or 1)
    plan = plan_context_compaction(assembled, keep)
    prepared = assembled
    summarized = False
    threshold = config.compaction_threshold_tokens
    triggered = not _fits(assembled, config) or (
        threshold is not None and estimate_tokens(assembled) > threshold
    )
    summarizer = config.async_summarizer
    if summarizer is not None and plan.removable and triggered:
        # 只把可压缩中段的深拷贝交给摘要器, 原始 history 对象不能被改写.
        summary = await summarizer.summarize(
            tuple(message.model_copy(deep=True) for message in plan.removable),
            run_config,
        )
        if not isinstance(summary, str) or not summary.strip():
            raise ContextPreparationError("Summary must be nonblank text.")
        summary = preserve_tool_facts(plan.removable, summary)
        prepared = apply_compaction_summary(plan, summary)
        summarized = True

    if not _fits(prepared, config) and not summarized:
        candidates = [index for index in turns if 0 < index <= len(plan.removable)]
        for start in candidates:
            facts = preserve_tool_facts(rest[:start], "")
            fact_messages = (SystemMessage(facts),) if facts else ()
            candidate = (*plan.leading_system, *fact_messages, *rest[start:])
            safe_boundaries(candidate)
            if _fits(candidate, config):
                prepared = candidate
                break
    if not _fits(prepared, config):
        raise ContextPreparationError(
            "Required rules, summary and recent turns exceed context budget."
        )
    safe_boundaries(prepared)
    return prepared
