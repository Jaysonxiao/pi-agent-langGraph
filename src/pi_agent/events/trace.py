"""Content-free trace projection for local operational diagnostics."""

from pi_agent.events.stream import StreamEvent


def sanitized_trace(event: StreamEvent) -> dict[str, object]:
    """Keep event shape, status and token counts; drop prompts and tool output."""
    trace: dict[str, object] = {
        "sequence": event.sequence,
        "kind": event.kind,
        "node": event.node,
    }
    status = event.payload.get("status")
    if isinstance(status, str):
        trace["status"] = status
    error = event.payload.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        if isinstance(code, str):
            trace["error_code"] = code
    usage = event.payload.get("usage")
    if isinstance(usage, dict):
        trace["usage"] = {
            key: value
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance((value := usage.get(key)), int) and not isinstance(value, bool)
        }
    return trace
