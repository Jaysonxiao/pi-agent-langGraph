"""Build ephemeral model-visible context from persisted messages and rules."""

from collections.abc import Sequence

from langchain_core.messages import AnyMessage, SystemMessage

from pi_agent.context.instructions import WorkspaceInstruction


def assemble_context_messages(
    messages: Sequence[AnyMessage],
    instructions: Sequence[WorkspaceInstruction],
) -> tuple[AnyMessage, ...]:
    """Return model input with workspace rules without mutating persisted history."""
    # 始终复制, 即使输入已是 tuple 也不能把原对象交回去给模型层.
    history = (*messages,)
    if not instructions:
        return history
    # 规则只作为一次性 SystemMessage 前置; 已有 system/human/ai 仍留在原位置.
    return (_render_instruction_message(instructions), *history)


def _render_instruction_message(instructions: Sequence[WorkspaceInstruction]) -> SystemMessage:
    blocks = [
        # POSIX 路径便于来源诊断, 也避免 Windows 反斜杠破坏路径匹配.
        f"{instruction.path.as_posix()}\n{instruction.content}"
        for instruction in instructions
    ]
    return SystemMessage(content="\n\n".join(blocks))
