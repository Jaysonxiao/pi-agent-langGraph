"""Typed tool definitions and the runtime registry."""

from pi_agent.tools.base import ExecutableTool, ToolDefinition
from pi_agent.tools.fake import AddArguments, RecordingAddHandler, create_add_tool
from pi_agent.tools.file_apply import AppliedFileChange, apply_approved_file_change
from pi_agent.tools.file_mutation import (
    EditArguments,
    FileChangePlanner,
    FileMutationError,
    PreparedFileChange,
    WriteArguments,
    apply_exact_replacement,
    to_pending_file_change,
)
from pi_agent.tools.output import BoundedText, TextOutputBudget
from pi_agent.tools.process import (
    ProcessArguments,
    ProcessExecutionError,
    ProcessResult,
    run_controlled_process,
)
from pi_agent.tools.read_only import (
    ListArguments,
    ReadArguments,
    SearchArguments,
    create_list_tool,
    create_read_tool,
    create_search_tool,
)
from pi_agent.tools.registry import ToolRegistry

__all__ = [
    "AddArguments",
    "AppliedFileChange",
    "BoundedText",
    "EditArguments",
    "ExecutableTool",
    "FileChangePlanner",
    "FileMutationError",
    "ListArguments",
    "PreparedFileChange",
    "ProcessArguments",
    "ProcessExecutionError",
    "ProcessResult",
    "ReadArguments",
    "RecordingAddHandler",
    "SearchArguments",
    "TextOutputBudget",
    "ToolDefinition",
    "ToolRegistry",
    "WriteArguments",
    "apply_approved_file_change",
    "apply_exact_replacement",
    "create_add_tool",
    "create_list_tool",
    "create_read_tool",
    "create_search_tool",
    "run_controlled_process",
    "to_pending_file_change",
]
