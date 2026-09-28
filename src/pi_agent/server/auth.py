"""Authentication prelude for the local remote protocol server."""

import asyncio
import hmac
import math
import os
from typing import Final

from pi_agent.protocol.transport import (
    AUTH_HEADER_BYTES,
    MAX_AUTH_TOKEN_BYTES,
    decode_auth_length,
    validate_auth_token,
)

REMOTE_TOKEN_ENV: Final = "PI_AGENT_REMOTE_TOKEN"
DEFAULT_AUTH_TIMEOUT_SECONDS = 5.0


class AuthenticationConfigurationError(ValueError):
    """The local server cannot start without a valid authentication token."""


def load_remote_token(token: str | None = None) -> bytes:
    """Read or validate the shared local token without retaining its text."""
    candidate = os.environ.get(REMOTE_TOKEN_ENV) if token is None else token
    if candidate is None:
        raise AuthenticationConfigurationError("Remote authentication token is required.")
    try:
        return validate_auth_token(candidate)
    except ValueError as error:
        raise AuthenticationConfigurationError(str(error)) from None


async def authenticate_connection(
    reader: asyncio.StreamReader,
    expected_token: bytes,
    *,
    timeout_seconds: float = DEFAULT_AUTH_TIMEOUT_SECONDS,
) -> bool:
    """在截止时间内读取并校验有界认证前导, 不消费后续协议字节。"""
    # 认证参数来自服务端配置; 无效配置直接拒绝, 避免异常值绕过认证边界。
    if (
        not isinstance(expected_token, bytes)
        or not 1 <= len(expected_token) <= MAX_AUTH_TOKEN_BYTES
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        return False

    try:
        async with asyncio.timeout(timeout_seconds):
            # readexactly 只消费指定长度, StreamReader 中合并到达的 hello 字节会留下。
            header = await reader.readexactly(AUTH_HEADER_BYTES)
            # 必须先校验头部声明长度, 再读取 token 正文, 防止按不可信长度读取。
            token_length = decode_auth_length(header)
            presented_token = await reader.readexactly(token_length)
    except (TimeoutError, asyncio.IncompleteReadError, ConnectionError, OSError, ValueError):
        # 包含超时、提前 EOF 及非法长度; 不向调用方暴露认证数据或解析细节。
        return False

    # 使用常量时间比较, 避免普通字节串比较泄露匹配位置的信息。
    return hmac.compare_digest(presented_token, expected_token)
