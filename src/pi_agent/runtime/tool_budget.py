"""Application-owned accounting, independent of tool execution or approval mode."""

from typing import Protocol


class ToolCallBudget(Protocol):
    def reserve(self, *, message_id: str, tool_call_id: str, tool_name: str) -> bool:
        """Admit an operation once, or replay its previous accounting decision."""
        ...
