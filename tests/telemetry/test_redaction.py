"""Red tests for the learner-owned M9.3.3 telemetry attribute redaction."""

from copy import deepcopy

from pi_agent.telemetry.redaction import redact_attributes


def test_redacts_sensitive_fields_recursively_without_mutating_input() -> None:
    attributes: dict[str, object] = {
        "thread_id": "thread-safe",
        "input_tokens": 14,
        "Authorization": "Bearer synthetic-api-secret",
        "nested": {
            "api-key": "synthetic-key",
            "Prompt": "private user prompt",
            "tool_calls": [
                {
                    "tool_name": "read",
                    "tool_args": {"path": "private/path.txt"},
                    "tool-output": "private file contents",
                }
            ],
        },
    }
    original = deepcopy(attributes)

    sanitized = redact_attributes(attributes)

    assert sanitized == {
        "thread_id": "thread-safe",
        "input_tokens": 14,
        "Authorization": "[REDACTED]",
        "nested": {
            "api-key": "[REDACTED]",
            "Prompt": "[REDACTED]",
            "tool_calls": [
                {
                    "tool_name": "read",
                    "tool_args": "[REDACTED]",
                    "tool-output": "[REDACTED]",
                }
            ],
        },
    }
    assert attributes == original


def test_redacted_mapping_contains_no_synthetic_sensitive_values() -> None:
    sanitized = redact_attributes(
        {
            "request": {
                "access_token": "synthetic-access-token",
                "messages": [{"content": "private conversation"}],
            },
            "metrics": {"output_tokens": 3, "latency_ms": 25},
        }
    )

    rendered = repr(sanitized)
    assert "synthetic-access-token" not in rendered
    assert "private conversation" not in rendered
    assert sanitized["metrics"] == {"output_tokens": 3, "latency_ms": 25}
