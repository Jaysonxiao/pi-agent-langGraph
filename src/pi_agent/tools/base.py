"""Provider-independent tool definition used by the M3 registry."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

ToolArgumentsT = TypeVar("ToolArgumentsT", bound=BaseModel)


class ToolArgumentError(Exception):
    """Separate model-supplied argument failures from handler failures."""

    def __init__(self, error: ValidationError) -> None:
        super().__init__("Tool arguments failed validation.")
        self.details: object = error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )


class ExecutableTool(Protocol):
    """Non-generic registry view of a validated tool."""

    @property
    def name(self) -> str:
        """Model-visible unique tool name."""
        ...

    @property
    def description(self) -> str:
        """Model-visible explanation of the tool."""
        ...

    def invoke(self, raw_args: Mapping[str, object]) -> str:
        """Validate raw model arguments and execute the handler."""
        ...


@dataclass(frozen=True, slots=True)
class ToolDefinition(Generic[ToolArgumentsT]):
    """Pair one Pydantic argument schema with one application handler."""

    name: str
    description: str
    args_schema: type[ToolArgumentsT]
    handler: Callable[[ToolArgumentsT], str]

    def __post_init__(self) -> None:
        """Keep registry keys unambiguous."""
        if not self.name or self.name != self.name.strip():
            raise ValueError("Tool name must be non-empty and have no surrounding whitespace.")

    def invoke(self, raw_args: Mapping[str, object]) -> str:
        """Validate before calling application code."""
        try:
            validated = self.args_schema.model_validate(raw_args)
        except ValidationError as exc:
            raise ToolArgumentError(exc) from exc
        return self.handler(validated)
