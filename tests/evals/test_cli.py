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
