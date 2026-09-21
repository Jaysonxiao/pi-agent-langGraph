"""JSONL serialization for stable runtime events."""

import json
from collections.abc import Iterable, Iterator

from pi_agent.closing import close_iterator
from pi_agent.events.stream import StreamEvent


def iter_jsonl(events: Iterable[StreamEvent]) -> Iterator[str]:
    """Serialize events lazily, yielding exactly one newline-terminated line each."""

    iterator = iter(events)
    try:
        for event in iterator:
            # 沿 StreamEvent 字段顺序做 JSON 投影; 不转义非 ASCII, 也不插入空格.
            payload = json.dumps(
                event.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"{payload}\n"
    finally:
        close_iterator(iterator)
