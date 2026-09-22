"""Insert a supplied compaction summary into ephemeral model context."""

from langchain_core.messages import AnyMessage, SystemMessage

from pi_agent.context.compaction import CompactionPlan


def apply_compaction_summary(
    plan: CompactionPlan,
    summary: str,
) -> tuple[AnyMessage, ...]:
    """Build temporary context from a plan and an already-produced summary."""
    # 没有可压缩中段就不注入, 摘要文本即使非空也只是调用方误传.
    if not plan.removable:
        return (*plan.leading_system, *plan.recent)

    if not summary.strip():
        raise ValueError("summary must not be blank when history was compacted.")

    # 摘要只夹在系统前缀和最近历史之间; 不回写 removable, 也不调用模型.
    return (
        *plan.leading_system,
        SystemMessage(content=summary),
        *plan.recent,
    )
