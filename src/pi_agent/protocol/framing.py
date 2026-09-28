"""Length-prefixed framing for an incremental byte stream.

Incremental decoding keeps only the incomplete frame between calls.
"""

from typing import Literal, NoReturn

from pi_agent.protocol.errors import FrameError

FRAME_HEADER_BYTES = 4
MAX_FRAME_BYTES = 0xFFFF_FFFF
DEFAULT_MAX_FRAME_BYTES = 1024 * 1024

DecoderState = Literal["open", "ended", "failed"]


def encode_frame(payload: bytes, *, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> bytes:
    """Prefix one non-empty payload with its unsigned 32-bit big-endian byte length."""
    _validate_max_frame_bytes(max_frame_bytes)
    if not isinstance(payload, bytes):
        raise TypeError("Frame payload must be bytes.")
    if not payload:
        raise FrameError("Frame payload must not be empty.")
    if len(payload) > max_frame_bytes:
        raise FrameError(f"Frame payload exceeds the configured limit of {max_frame_bytes} bytes.")
    return len(payload).to_bytes(FRAME_HEADER_BYTES, byteorder="big") + payload


class FrameDecoder:
    """Turn arbitrary byte chunks into complete, bounded frame payloads."""

    def __init__(self, *, max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> None:
        _validate_max_frame_bytes(max_frame_bytes)
        self._max_frame_bytes = max_frame_bytes
        self._state: DecoderState = "open"
        # feed() owns the parsing of these bounded, incomplete pieces.
        self._header = bytearray()
        self._payload = bytearray()
        self._expected_payload_bytes: int | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        """返回本次输入中完整的 payload,并保留尚未接收完整的帧。"""
        self._require_open()
        if not isinstance(chunk, bytes):
            raise TypeError("Frame chunk must be bytes.")

        payloads: list[bytes] = []
        offset = 0
        while offset < len(chunk):
            if self._expected_payload_bytes is None:
                # 逐步收齐 4 字节头;不把整个输入块复制到内部缓冲区。
                header_bytes_needed = FRAME_HEADER_BYTES - len(self._header)
                bytes_to_copy = min(header_bytes_needed, len(chunk) - offset)
                self._header.extend(chunk[offset : offset + bytes_to_copy])
                offset += bytes_to_copy
                if len(self._header) < FRAME_HEADER_BYTES:
                    break

                # 头部使用无符号大端整数,先校验再接收正文,避免按不可信长度分配空间。
                expected = int.from_bytes(self._header, byteorder="big", signed=False)
                self._header.clear()
                if expected == 0:
                    self._fail("Frame has a zero-length payload.")
                if expected > self._max_frame_bytes:
                    self._fail(
                        f"Frame payload exceeds the configured limit of "
                        f"{self._max_frame_bytes} bytes."
                    )
                self._expected_payload_bytes = expected

            # 只追加当前帧实际还缺少的字节,跨 feed 的部分正文留在 _payload 中。
            assert self._expected_payload_bytes is not None
            payload_bytes_needed = self._expected_payload_bytes - len(self._payload)
            bytes_to_copy = min(payload_bytes_needed, len(chunk) - offset)
            self._payload.extend(chunk[offset : offset + bytes_to_copy])
            offset += bytes_to_copy
            if len(self._payload) < self._expected_payload_bytes:
                break

            # 正文完整后输出独立 bytes,再清空状态继续解析同一块中的下一帧。
            payloads.append(bytes(self._payload))
            self._payload.clear()
            self._expected_payload_bytes = None

        return payloads

    def finish(self) -> None:
        """Mark the stream ended, rejecting a partial header or payload."""
        self._require_open()
        if self._header or self._expected_payload_bytes is not None:
            self._fail("Truncated frame at end of stream.")
        self._state = "ended"

    def _require_open(self) -> None:
        if self._state == "ended":
            raise FrameError("Frame decoder has ended.")
        if self._state == "failed":
            raise FrameError("Frame decoder has failed.")

    def _fail(self, message: str) -> NoReturn:
        """Clear partial data and make the decoder terminal after a protocol error."""
        self._state = "failed"
        self._header.clear()
        self._payload.clear()
        self._expected_payload_bytes = None
        raise FrameError(message)


def _validate_max_frame_bytes(value: int) -> None:
    """Require a positive integer bound that fits in the four-byte header."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_frame_bytes must be an integer.")
    if not 1 <= value <= MAX_FRAME_BYTES:
        raise ValueError(f"max_frame_bytes must be between 1 and {MAX_FRAME_BYTES}.")
