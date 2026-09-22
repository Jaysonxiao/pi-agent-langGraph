"""Unit tests for stable session-to-thread configuration."""

import pytest

from pi_agent.sessions import checkpoint_config, session_config


def test_session_config_maps_id_without_rewriting_it() -> None:
    assert session_config("session-123") == {"configurable": {"thread_id": "session-123"}}


@pytest.mark.parametrize("session_id", ["", "   ", " leading", "trailing ", "x" * 256])
def test_session_config_rejects_ambiguous_or_nonportable_ids(session_id: str) -> None:
    with pytest.raises(ValueError, match="Session id"):
        session_config(session_id)


def test_checkpoint_config_addresses_one_version_of_a_session() -> None:
    assert checkpoint_config("session-123", "checkpoint-456") == {
        "configurable": {
            "thread_id": "session-123",
            "checkpoint_id": "checkpoint-456",
        }
    }


@pytest.mark.parametrize("checkpoint_id", ["", "   ", " leading", "trailing "])
def test_checkpoint_config_rejects_ambiguous_ids(checkpoint_id: str) -> None:
    with pytest.raises(ValueError, match="Checkpoint id"):
        checkpoint_config("session-123", checkpoint_id)
