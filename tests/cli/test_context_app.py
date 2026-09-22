"""Context inspection must use the pipeline without running a graph or model."""

import json
from pathlib import Path

import pytest

from pi_agent.cli import app


def test_context_inspect_reports_sources_and_budgets_without_model(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> None:
        pytest.fail("inspection must not create a model or graph")

    monkeypatch.setattr(app, "build_minimal_graph", forbidden)
    monkeypatch.setattr(app, "FakeChatModel", forbidden)
    (tmp_path / "AGENTS.md").write_text("PRIVATE_RULE_TEXT", encoding="utf-8")
    assert app.main(["context", "inspect", "--provider", "fake", "--workspace", str(tmp_path)]) == 0
    raw = capsys.readouterr().out
    result = json.loads(raw)
    assert len(result["instruction_sources"]) == 1
    assert result["message_roles"] == ["system", "human"]
    assert result["prepared_bytes"] > 0 and result["estimated_prepared_tokens"] > 0
    assert "PRIVATE_RULE_TEXT" not in raw


def test_context_inspect_fails_for_impossible_budget(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert app.main(["context", "inspect", "--workspace", str(tmp_path), "--max-bytes", "1"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "context_error"
