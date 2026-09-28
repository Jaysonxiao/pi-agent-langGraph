"""Strict JSON payload parsing and serialization for protocol DTOs."""

import json
from typing import Any, NoReturn, TypeVar

from pydantic import TypeAdapter, ValidationError

from pi_agent.protocol.errors import ProtocolValidationError
from pi_agent.protocol.framing import DEFAULT_MAX_FRAME_BYTES
from pi_agent.protocol.messages import (
    CLIENT_MESSAGE_ADAPTER,
    SERVER_MESSAGE_ADAPTER,
    ClientMessage,
    ServerMessage,
)

MessageT = TypeVar("MessageT")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _invalid_message()
        value[key] = item
    return value


def _reject_non_finite_number(value: str) -> NoReturn:
    del value
    _invalid_message()


def _load_json_payload(payload: bytes, *, max_payload_bytes: int) -> Any:
    if (
        not isinstance(payload, bytes)
        or isinstance(max_payload_bytes, bool)
        or not isinstance(max_payload_bytes, int)
        or not 1 <= max_payload_bytes <= DEFAULT_MAX_FRAME_BYTES
    ):
        _invalid_message()
    if not payload or len(payload) > max_payload_bytes:
        _invalid_message()
    try:
        text = payload.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        _invalid_message()


def _validate_message(adapter: TypeAdapter[MessageT], value: Any) -> MessageT:
    try:
        return adapter.validate_python(value, strict=True)
    except (ValidationError, ValueError, TypeError, RecursionError):
        _invalid_message()


def _invalid_message() -> NoReturn:
    raise ProtocolValidationError() from None


def decode_client_message(
    payload: bytes, *, max_payload_bytes: int = DEFAULT_MAX_FRAME_BYTES
) -> ClientMessage:
    """安全解析一条客户端 payload,并校验为严格的入站 DTO。"""
    # 先检查字节类型、UTF-8、JSON 格式、重复键及长度上限,不向异常中带入原始内容。
    value = _load_json_payload(payload, max_payload_bytes=max_payload_bytes)
    # 使用严格的客户端联合类型适配器,校验方向、字段和类型,并统一隐藏校验细节。
    return _validate_message(CLIENT_MESSAGE_ADAPTER, value)


def decode_server_message(
    payload: bytes, *, max_payload_bytes: int = DEFAULT_MAX_FRAME_BYTES
) -> ServerMessage:
    """Decode a server payload, rejecting malformed or wrong-direction DTOs."""
    value = _load_json_payload(payload, max_payload_bytes=max_payload_bytes)
    return _validate_message(SERVER_MESSAGE_ADAPTER, value)


def _encode_message(
    adapter: TypeAdapter[MessageT], message: Any, *, max_payload_bytes: int
) -> bytes:
    if (
        isinstance(max_payload_bytes, bool)
        or not isinstance(max_payload_bytes, int)
        or not 1 <= max_payload_bytes <= DEFAULT_MAX_FRAME_BYTES
    ):
        _invalid_message()
    validated = _validate_message(adapter, message)
    try:
        value = adapter.dump_python(validated, mode="json")
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _invalid_message()
    if not payload or len(payload) > max_payload_bytes:
        _invalid_message()
    return payload


def encode_client_message(
    message: ClientMessage, *, max_payload_bytes: int = DEFAULT_MAX_FRAME_BYTES
) -> bytes:
    """Validate and encode one client DTO as bounded compact UTF-8 JSON."""
    return _encode_message(CLIENT_MESSAGE_ADAPTER, message, max_payload_bytes=max_payload_bytes)


def encode_server_message(
    message: ServerMessage, *, max_payload_bytes: int = DEFAULT_MAX_FRAME_BYTES
) -> bytes:
    """Validate and encode one server DTO as bounded compact UTF-8 JSON."""
    return _encode_message(SERVER_MESSAGE_ADAPTER, message, max_payload_bytes=max_payload_bytes)
