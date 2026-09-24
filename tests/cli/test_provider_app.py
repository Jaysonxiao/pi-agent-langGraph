"""Red tests for the learner-owned M8.8-R3 provider CLI options boundary."""

from argparse import Namespace
from pathlib import Path

import pytest

from pi_agent.cli.provider import ProviderCliOptions, resolve_provider_cli_options


def test_provider_options_preserve_explicit_runtime_paths(tmp_path: Path) -> None:
    args = Namespace(
        provider="fake",
        prompt="hello",
        events="jsonl",
        database=tmp_path / "sessions.sqlite",
        session_id="session-1",
        workspace=tmp_path,
    )

    options = resolve_provider_cli_options(args)

    assert options == ProviderCliOptions(
        provider="fake",
        prompt="hello",
        events="jsonl",
        database=tmp_path / "sessions.sqlite",
        session_id="session-1",
        workspace=tmp_path,
    )


def test_provider_options_reject_missing_database_or_session() -> None:
    base = {
        "provider": "fake",
        "prompt": "hello",
        "events": "text",
        "database": None,
        "session_id": "",
        "workspace": Path.cwd(),
    }

    with pytest.raises(ValueError):
        resolve_provider_cli_options(Namespace(**base))


def test_provider_options_do_not_accept_secret_values() -> None:
    args = Namespace(
        provider="compatible",
        prompt="hello",
        events="text",
        database=Path("sessions.sqlite"),
        session_id="session-1",
        workspace=Path.cwd(),
        api_key="synthetic-secret",
    )

    options = resolve_provider_cli_options(args)

    assert not hasattr(options, "api_key")
