"""Client-side snapshot cache with connection-generation and server-revision guards."""

from pi_agent.protocol.messages import ServerEvent, SessionSnapshot, SnapshotEvent


class ClientState:
    """Cache authoritative snapshots while rejecting stale connection data."""

    def __init__(self) -> None:
        self._connection_generation = 0
        self._server_epoch: str | None = None
        self._snapshots: dict[str, SessionSnapshot] = {}
        self._stale_sessions: set[str] = set()

    @property
    def connection_generation(self) -> int:
        return self._connection_generation

    @property
    def server_epoch(self) -> str | None:
        return self._server_epoch

    def begin_connection(self) -> int:
        """Advance local connection identity and mark retained snapshots stale."""
        self._connection_generation += 1
        self._stale_sessions.update(self._snapshots)
        return self._connection_generation

    def accept_server_epoch(self, generation: int, server_epoch: str) -> bool:
        """Accept handshake metadata only from the current connection."""
        if generation != self._connection_generation:
            return False
        if self._server_epoch != server_epoch:
            self._server_epoch = server_epoch
            self._snapshots.clear()
            self._stale_sessions.clear()
        return True

    def mark_disconnected(self, generation: int) -> None:
        """Mark current cached state stale without erasing its last known value."""
        if generation == self._connection_generation:
            self._stale_sessions.update(self._snapshots)

    def apply_snapshot(self, snapshot: SessionSnapshot, generation: int) -> bool:
        """Apply a snapshot from the active connection unless its revision is old."""
        if generation != self._connection_generation:
            return False
        if self._server_epoch != snapshot.server_epoch:
            self._server_epoch = snapshot.server_epoch
            self._snapshots.clear()
            self._stale_sessions.clear()
        previous = self._snapshots.get(snapshot.session_id)
        if previous is not None and snapshot.revision < previous.revision:
            return False
        self._snapshots[snapshot.session_id] = snapshot
        self._stale_sessions.discard(snapshot.session_id)
        return True

    def apply_event(self, event: ServerEvent, generation: int) -> bool:
        """Apply only snapshot-bearing events; progress does not mutate authority."""
        if generation != self._connection_generation:
            return False
        if isinstance(event, SnapshotEvent):
            return self.apply_snapshot(event.snapshot, generation)
        return True

    def get_snapshot(self, session_id: str) -> SessionSnapshot | None:
        return self._snapshots.get(session_id)

    def is_stale(self, session_id: str) -> bool:
        return session_id in self._stale_sessions

    def clear_session(self, session_id: str) -> None:
        self._snapshots.pop(session_id, None)
        self._stale_sessions.discard(session_id)
