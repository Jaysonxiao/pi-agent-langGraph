"""Contract tests for the M4 learner-owned text budget."""

import pytest

from pi_agent.tools import TextOutputBudget


def test_output_budget_rejects_non_positive_limits() -> None:
    with pytest.raises(ValueError, match="max_lines"):
        TextOutputBudget(max_lines=0)
    with pytest.raises(ValueError, match="max_bytes"):
        TextOutputBudget(max_bytes=0)


def test_output_budget_preserves_text_that_fits() -> None:
    result = TextOutputBudget(max_lines=3, max_bytes=20).apply("alpha\nbeta")

    assert result.content == "alpha\nbeta"
    assert result.truncated is False
    assert result.truncated_by is None
    assert (result.total_lines, result.output_lines) == (2, 2)
    assert (result.total_bytes, result.output_bytes) == (10, 10)
    assert result.render() == "alpha\nbeta"


def test_output_budget_truncates_at_the_line_limit() -> None:
    result = TextOutputBudget(max_lines=2, max_bytes=100).apply("alpha\nbeta\ngamma")

    assert result.content == "alpha\nbeta"
    assert result.truncated_by == "lines"
    assert (result.total_lines, result.output_lines) == (3, 2)
    assert "[Output truncated by lines:" in result.render()


def test_output_budget_counts_utf8_bytes_and_keeps_whole_lines() -> None:
    result = TextOutputBudget(max_lines=10, max_bytes=5).apply("a\n你\nb")

    assert result.content == "a\n你"
    assert result.truncated_by == "bytes"
    assert (result.total_bytes, result.output_bytes) == (7, 5)
    assert result.first_line_exceeds_budget is False


def test_output_budget_omits_an_oversized_first_line() -> None:
    result = TextOutputBudget(max_lines=10, max_bytes=5).apply("你你\nnext")

    assert result.content == ""
    assert result.truncated_by == "bytes"
    assert result.output_lines == 0
    assert result.output_bytes == 0
    assert result.first_line_exceeds_budget is True
    assert result.render() == "[Output omitted: first line exceeds 5 UTF-8 bytes.]"
