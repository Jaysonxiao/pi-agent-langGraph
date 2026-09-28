"""Project completed tool hooks into an ordered evaluation observation."""

from collections.abc import Sequence

from pi_agent.extensions import HookEvent


def collect_tool_names(events: Sequence[HookEvent]) -> tuple[str, ...]:
    """Keep successful after_tool events, once per (thread, run, call) identity.

    Preserve arrival order, including repeated names from distinct calls.
    Do not sort by sequence: sequences restart for each run. The validated
    HookEvent boundary guarantees tool events have a name and call ID.
    Input events must remain unchanged. Empty/no-success input returns ().
    """
    tool_names: list[str] = []
    seen_calls: set[tuple[str, str, str]] = set()

    for event in events:
        if event.phase != "after_tool" or event.outcome != "completed":
            continue
        # 类型定义允许 None;显式收窄以防御不完整的观测输入.
        if event.tool_name is None or event.tool_call_id is None:
            continue

        identity = (event.thread_id, event.run_id, event.tool_call_id)
        if identity in seen_calls:
            continue

        # 保持到达顺序;按调用身份去重而不是按工具名去重.
        seen_calls.add(identity)
        tool_names.append(event.tool_name)

    return tuple(tool_names)
