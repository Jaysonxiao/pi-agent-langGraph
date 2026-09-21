"""Harmless deterministic tools used by the M3 teaching loop."""

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from pi_agent.tools.base import ToolDefinition


class AddArguments(BaseModel):
    """Strict arguments for the fake integer addition tool."""

    model_config = ConfigDict(extra="forbid")

    left: int
    right: int


@dataclass(slots=True)
class RecordingAddHandler:
    """Record validated calls so tests can assert the execution boundary."""

    calls: list[AddArguments] = field(default_factory=list)

    def __call__(self, args: AddArguments) -> str:
        """Return a deterministic, model-visible result."""
        self.calls.append(args)
        return str(args.left + args.right)


def create_add_tool(handler: RecordingAddHandler) -> ToolDefinition[AddArguments]:
    """Create the fake add tool without hiding its schema or handler."""
    return ToolDefinition(
        name="add",
        description="Add two integers.",
        args_schema=AddArguments,
        handler=handler,
    )
