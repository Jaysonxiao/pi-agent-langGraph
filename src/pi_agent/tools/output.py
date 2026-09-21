"""Shared text-output budgets for model-visible tool results."""

from dataclasses import dataclass
from typing import Literal

TruncationReason = Literal["lines", "bytes"]


@dataclass(frozen=True, slots=True)
class BoundedText:
    """Text plus deterministic metadata describing an applied output budget."""

    content: str
    truncated_by: TruncationReason | None
    total_lines: int
    total_bytes: int
    output_lines: int
    output_bytes: int
    max_lines: int
    max_bytes: int
    first_line_exceeds_budget: bool = False

    @property
    def truncated(self) -> bool:
        """Whether the original text exceeded either configured limit."""
        return self.truncated_by is not None

    def render(self) -> str:
        """Render content with a model-visible continuation/truncation hint."""
        if not self.truncated:
            return self.content
        if self.first_line_exceeds_budget:
            return f"[Output omitted: first line exceeds {self.max_bytes} UTF-8 bytes.]"

        marker = (
            f"[Output truncated by {self.truncated_by}: showing "
            f"{self.output_lines}/{self.total_lines} lines and "
            f"{self.output_bytes}/{self.total_bytes} UTF-8 bytes.]"
        )
        return f"{self.content}\n\n{marker}" if self.content else marker


@dataclass(frozen=True, slots=True)
class TextOutputBudget:
    """Keep the head of text within independent line and UTF-8 byte limits."""

    max_lines: int = 2_000
    max_bytes: int = 50 * 1_024

    def __post_init__(self) -> None:
        """Reject configurations that could never emit a complete line."""
        if self.max_lines <= 0:
            raise ValueError("max_lines must be greater than zero.")
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero.")

    def apply(self, text: str) -> BoundedText:
        """Return the largest whole-line head that fits both limits.

        M4 learner exercise: implement the common result boundary used by read,
        list, and search. See ``docs/acceptance/M4.md`` for the complete contract.
        """
        total_bytes = len(text.encode("utf-8"))
        lines = text.splitlines()
        total_lines = len(lines)

        if total_lines <= self.max_lines and total_bytes <= self.max_bytes:
            return BoundedText(
                content=text,
                truncated_by=None,
                total_lines=total_lines,
                total_bytes=total_bytes,
                output_lines=total_lines,
                output_bytes=total_bytes,
                max_lines=self.max_lines,
                max_bytes=self.max_bytes,
            )

        selected_lines: list[str] = []
        output_bytes = 0
        truncated_by: TruncationReason = "lines"

        for line in lines:
            if len(selected_lines) >= self.max_lines:
                truncated_by = "lines"
                break

            separator_bytes = 1 if selected_lines else 0
            line_bytes = len(line.encode("utf-8"))
            next_bytes = output_bytes + separator_bytes + line_bytes
            if next_bytes > self.max_bytes:
                truncated_by = "bytes"
                break

            selected_lines.append(line)
            output_bytes = next_bytes

        content = "\n".join(selected_lines)
        return BoundedText(
            content=content,
            truncated_by=truncated_by,
            total_lines=total_lines,
            total_bytes=total_bytes,
            output_lines=len(selected_lines),
            output_bytes=output_bytes,
            max_lines=self.max_lines,
            max_bytes=self.max_bytes,
            first_line_exceeds_budget=not selected_lines and truncated_by == "bytes",
        )
