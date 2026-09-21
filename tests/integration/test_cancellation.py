"""Real graph evidence for cooperative cancellation of a projected stream."""

from collections.abc import Iterable
from typing import cast

from langchain_core.messages import AIMessage

from pi_agent.cli import CancellationToken, iter_cancellable
from pi_agent.closing import close_iterator
from pi_agent.domain import create_initial_state
from pi_agent.events import project_stream_chunks
from pi_agent.graph import RunContext, build_minimal_graph
from pi_agent.models.fake import ScriptedChatModel


def test_cancelling_real_projected_stream_closes_source() -> None:
    raw_chunks = cast(
        Iterable[tuple[str, object]],
        build_minimal_graph().stream(
            create_initial_state("hello"),
            context=RunContext(
                model=ScriptedChatModel([AIMessage(content="done", id="assistant-final")])
            ),
            stream_mode=["updates", "messages"],
        ),
    )

    class TrackedRawStream:
        def __init__(self, source: Iterable[tuple[str, object]]) -> None:
            self._iterator = iter(source)
            self.close_calls = 0

        def __iter__(self) -> "TrackedRawStream":
            return self

        def __next__(self) -> tuple[str, object]:
            return next(self._iterator)

        def close(self) -> None:
            self.close_calls += 1
            close_iterator(self._iterator)

    tracked_raw = TrackedRawStream(raw_chunks)
    token = CancellationToken()
    events = iter_cancellable(project_stream_chunks(tracked_raw), token)

    assert next(events).kind == "message"
    token.cancel()
    assert list(events) == []
    assert tracked_raw.close_calls == 1
