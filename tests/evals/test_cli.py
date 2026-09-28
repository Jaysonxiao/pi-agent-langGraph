"""Acceptance contract for the learner-owned M9.5 fake eval CLI."""

import json

import pytest

from pi_agent.cli import main


def test_fake_smoke_cli_emits_repeatable_safe_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = ["eval", "--suite", "smoke", "--provider", "fake"]

    first_exit_code = main(arguments)
    first_output = capsys.readouterr().out
    second_exit_code = main(arguments)
    second_output = capsys.readouterr().out

    assert first_exit_code == 0
    assert second_exit_code == 0
    assert first_output == second_output
    report = json.loads(first_output)
    assert report["suite"] == "smoke"
    assert report["total"] >= 1
    assert report["passed"] == report["total"]
    assert "hello" not in first_output
    assert "fake reply" not in first_output


def test_fake_tools_cli_emits_repeatable_safe_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = ["eval", "--suite", "tools", "--provider", "fake"]
    first_exit_code = main(arguments)
    first = capsys.readouterr()
    second_exit_code = main(arguments)
    second = capsys.readouterr()

    assert first_exit_code == second_exit_code == 0
    assert first.err == second.err == ""
    assert first.out == second.out
    report = json.loads(first.out)
    assert report["suite"] == "tools"
    assert report["total"] == report["passed"] == 1
    assert report["results"][0]["checks"]["tool_names_match"] is True
    assert "synthetic M11 probe" not in first.out
    assert "List the workspace" not in first.out
