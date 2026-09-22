"""M6 session-command wiring tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pi_agent.cli import app as cli_app
from pi_agent.sessions import SqliteSessionCatalog


def test_session_list_reads_catalog_in_stable_order_without_building_a_graph(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "checkpoints.sqlite"
    timestamps = iter(
        (
            datetime(2026, 9, 21, 10, 0, tzinfo=UTC),
            datetime(2026, 9, 21, 10, 1, tzinfo=UTC) + timedelta(minutes=1),
        )
    )
    catalog = SqliteSessionCatalog(database_path, clock=lambda: next(timestamps))
    catalog.record_session("older")
    catalog.record_session("newer")
    monkeypatch.setattr(
        cli_app,
        "build_minimal_graph",
        lambda: pytest.fail("session list must not construct an agent graph"),
    )

    exit_code = cli_app.main(["session", "list", "--database", str(database_path)])

    assert exit_code == cli_app.EXIT_SUCCESS
    assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
        {
            "session_id": "newer",
            "created_at": "2026-09-21T10:02:00+00:00",
            "updated_at": "2026-09-21T10:02:00+00:00",
        },
        {
            "session_id": "older",
            "created_at": "2026-09-21T10:00:00+00:00",
            "updated_at": "2026-09-21T10:00:00+00:00",
        },
    ]
