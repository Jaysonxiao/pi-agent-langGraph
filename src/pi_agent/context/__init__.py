"""Context discovery, assembly, budgeting, and compaction boundaries."""

from pi_agent.context.assembly import assemble_context_messages
from pi_agent.context.async_runtime import prepare_model_messages_async
from pi_agent.context.async_summarizer import AsyncModelSummarizer, AsyncSummarizer
from pi_agent.context.budget import BoundedContext, fit_context_messages
from pi_agent.context.compaction import CompactionPlan, plan_context_compaction
from pi_agent.context.instructions import (
    INSTRUCTION_FILENAME,
    PI_INSTRUCTION_FILENAME,
    InstructionLoadError,
    WorkspaceInstruction,
    discover_workspace_instruction_files,
    load_workspace_instructions,
)
from pi_agent.context.runtime import (
    ContextConfig,
    ContextPreparationError,
    PreparedContext,
    inspect_model_context,
    prepare_model_messages,
)
from pi_agent.context.summarizer import ModelSummarizer
from pi_agent.context.summary import apply_compaction_summary

__all__ = [
    "INSTRUCTION_FILENAME",
    "PI_INSTRUCTION_FILENAME",
    "AsyncModelSummarizer",
    "AsyncSummarizer",
    "BoundedContext",
    "CompactionPlan",
    "ContextConfig",
    "ContextPreparationError",
    "InstructionLoadError",
    "ModelSummarizer",
    "PreparedContext",
    "WorkspaceInstruction",
    "apply_compaction_summary",
    "assemble_context_messages",
    "discover_workspace_instruction_files",
    "fit_context_messages",
    "inspect_model_context",
    "load_workspace_instructions",
    "plan_context_compaction",
    "prepare_model_messages",
    "prepare_model_messages_async",
]
