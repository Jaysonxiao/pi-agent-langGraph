"""Acceptance tests for stable JSONL event serialization."""

from pi_agent.events import StreamEvent, iter_jsonl


def test_jsonl_serializes_one_compact_utf8_event_per_line() -> None:
    event = StreamEvent(
        sequence=0,
        kind="progress",
        node="model",
        payload={"message": "调用模型", "completed": 0, "total": 1},
    )

    assert list(iter_jsonl([event])) == [
        '{"sequence":0,"kind":"progress","node":"model",'
        '"payload":{"message":"调用模型","completed":0,"total":1}}\n'
    ]


def test_jsonl_preserves_event_order_and_does_not_add_extra_lines() -> None:
    events = [
        StreamEvent(
            sequence=2,
            kind="message",
            node="model",
            payload={"role": "assistant", "content": "done", "is_chunk": False},
        ),
        StreamEvent(
            sequence=3,
            kind="state_update",
            node="model",
            payload={"status": "completed", "error": None},
        ),
    ]

    assert list(iter_jsonl(events)) == [
        '{"sequence":2,"kind":"message","node":"model",'
        '"payload":{"role":"assistant","content":"done","is_chunk":false}}\n',
        '{"sequence":3,"kind":"state_update","node":"model",'
        '"payload":{"status":"completed","error":null}}\n',
    ]
