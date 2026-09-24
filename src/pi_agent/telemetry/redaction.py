"""Recursive, copy-on-write redaction for telemetry attributes."""

from collections.abc import Mapping

_REDACTED = "[REDACTED]"
# 比较前会把 key 转成小写并把连字符换成下划线, 因此 Authorization / api-key 都能命中.
_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "access_token",
        "refresh_token",
        "token",
        "password",
        "secret",
        "prompt",
        "messages",
        "tool_args",
        "arguments",
        "tool_output",
        "content",
    }
)


def _normalize_key(name: str) -> str:
    return name.lower().replace("-", "_")


def _is_sensitive(name: str) -> bool:
    # 整键匹配, 避免把 input_tokens / output_tokens 误判成 token.
    return _normalize_key(name) in _SENSITIVE_KEYS


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return redact_attributes(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def redact_attributes(attributes: Mapping[str, object], /) -> dict[str, object]:
    """Return a new mapping with sensitive fields replaced; never mutate the input."""
    sanitized: dict[str, object] = {}
    for key, value in attributes.items():
        if _is_sensitive(key):
            # 敏感字段整段替换, 不再向下遍历, 以免 key 名或嵌套值泄漏进 sink.
            sanitized[key] = _REDACTED
        else:
            sanitized[key] = _redact_value(value)
    return sanitized
