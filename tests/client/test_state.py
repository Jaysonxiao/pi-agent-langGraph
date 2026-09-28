"""Client snapshot cache and stale-state boundaries."""

from pi_agent.client.state import ClientState
from pi_agent.protocol.messages import DisplayMessage, SessionSnapshot, SnapshotEvent


def _snapshot(
    *, session_id: str = "session-1", epoch: str = "epoch-1", revision: int = 1
) -> SessionSnapshot:
    return SessionSnapshot(
        session_id=session_id,
        server_epoch=epoch,
        revision=revision,
        checkpoint_id=None,
        graph_status="idle",
        run_phase="idle",
        run_outcome=None,
        active_run_id=None,
        message_count=1,
        messages=(DisplayMessage(message_id="message-1", role="assistant", text="ready"),),
        truncated=False,
    )


def test_same_epoch_old_revision_cannot_replace_new_snapshot() -> None:
    state = ClientState()
    generation = state.begin_connection()
    assert state.accept_server_epoch(generation, "epoch-1")
    newest = _snapshot(revision=3)
    older = _snapshot(revision=2)

    assert state.apply_snapshot(newest, generation)
    assert not state.apply_snapshot(older, generation)
    assert state.get_snapshot("session-1") == newest


def test_new_server_epoch_resets_revision_comparison_and_cache() -> None:
    state = ClientState()
    first_generation = state.begin_connection()
    state.accept_server_epoch(first_generation, "epoch-1")
    state.apply_snapshot(_snapshot(revision=30), first_generation)

    second_generation = state.begin_connection()
    assert state.is_stale("session-1")
    assert state.accept_server_epoch(second_generation, "epoch-2")
    replacement = _snapshot(epoch="epoch-2", revision=1)

    assert state.get_snapshot("session-1") is None
    assert state.apply_snapshot(replacement, second_generation)
    assert not state.is_stale("session-1")
    assert state.get_snapshot("session-1") == replacement


def test_disconnect_retains_last_snapshot_and_marks_it_stale() -> None:
    state = ClientState()
    generation = state.begin_connection()
    state.accept_server_epoch(generation, "epoch-1")
    cached = _snapshot()
    state.apply_snapshot(cached, generation)

    state.mark_disconnected(generation)

    assert state.get_snapshot("session-1") == cached
    assert state.is_stale("session-1")


def test_old_connection_snapshot_event_is_ignored_after_reconnect() -> None:
    state = ClientState()
    old_generation = state.begin_connection()
    state.accept_server_epoch(old_generation, "epoch-1")
    new_generation = state.begin_connection()
    state.accept_server_epoch(new_generation, "epoch-1")
    old_event = SnapshotEvent(type="event", event="snapshot", snapshot=_snapshot(revision=9))

    assert not state.apply_event(old_event, old_generation)
    assert state.get_snapshot("session-1") is None
