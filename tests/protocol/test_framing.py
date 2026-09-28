"""M10.1 contracts for bounded length-prefix framing."""

import pytest

from pi_agent.protocol import (
    DEFAULT_MAX_FRAME_BYTES,
    FRAME_HEADER_BYTES,
    FrameDecoder,
    FrameError,
    encode_frame,
)


def test_encode_frame_uses_unsigned_big_endian_byte_length() -> None:
    frame = encode_frame(b"abc")

    assert frame == b"\x00\x00\x00\x03abc"
    assert len(frame[:FRAME_HEADER_BYTES]) == FRAME_HEADER_BYTES


def test_encode_frame_rejects_empty_or_oversized_payload() -> None:
    with pytest.raises(FrameError, match="must not be empty"):
        encode_frame(b"")
    with pytest.raises(FrameError, match="exceeds"):
        encode_frame(b"four", max_frame_bytes=3)


@pytest.mark.parametrize("value", [0, -1, 0x1_0000_0000])
def test_frame_limit_must_fit_the_unsigned_header(value: int) -> None:
    with pytest.raises(ValueError, match="max_frame_bytes"):
        FrameDecoder(max_frame_bytes=value)


@pytest.mark.parametrize("value", [True, 1.5, "12"])
def test_frame_limit_rejects_coercible_non_integers(value: object) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        FrameDecoder(max_frame_bytes=value)  # type: ignore[arg-type]


def test_frame_limit_defaults_to_one_mibibyte() -> None:
    assert DEFAULT_MAX_FRAME_BYTES == 1024 * 1024


def test_feed_rejects_non_bytes_without_poisoning_decoder() -> None:
    decoder = FrameDecoder()

    with pytest.raises(TypeError, match="must be bytes"):
        decoder.feed(bytearray(b"frame"))  # type: ignore[arg-type]

    assert decoder.feed(b"") == []


def test_feed_waits_for_a_split_header_and_payload() -> None:
    decoder = FrameDecoder()
    frame = encode_frame(b"payload")

    assert decoder.feed(frame[:2]) == []
    assert decoder.feed(frame[2:6]) == []
    assert decoder.feed(frame[6:]) == [b"payload"]


def test_feed_accepts_a_frame_arriving_one_byte_at_a_time() -> None:
    decoder = FrameDecoder()
    frame = encode_frame("请读取 probe.txt 并总结".encode())
    payloads: list[bytes] = []

    for byte in frame:
        payloads.extend(decoder.feed(bytes([byte])))

    assert payloads == ["请读取 probe.txt 并总结".encode()]


def test_feed_preserves_multiple_coalesced_frames_in_order() -> None:
    decoder = FrameDecoder()
    first = encode_frame(b"request-1")
    second = encode_frame(b"request-2")

    assert decoder.feed(first + second) == [b"request-1", b"request-2"]


def test_feed_handles_completed_frame_followed_by_partial_frame() -> None:
    decoder = FrameDecoder()
    first = encode_frame(b"complete")
    second = encode_frame(b"later")

    assert decoder.feed(first + second[:6]) == [b"complete"]
    assert decoder.feed(second[6:]) == [b"later"]


def test_feed_counts_utf8_payload_limit_in_bytes() -> None:
    payload = "界".encode()
    decoder = FrameDecoder(max_frame_bytes=len(payload))

    assert decoder.feed(encode_frame(payload, max_frame_bytes=len(payload))) == [payload]


def test_feed_rejects_zero_length_frame_and_becomes_terminal() -> None:
    decoder = FrameDecoder()

    with pytest.raises(FrameError, match="zero-length"):
        decoder.feed(b"\x00\x00\x00\x00")
    with pytest.raises(FrameError, match="has failed"):
        decoder.feed(encode_frame(b"later"))


def test_feed_rejects_oversized_header_before_receiving_its_body() -> None:
    decoder = FrameDecoder(max_frame_bytes=8)

    with pytest.raises(FrameError, match="exceeds"):
        decoder.feed(b"\x00\x00\x00\x09")
    with pytest.raises(FrameError, match="has failed"):
        decoder.feed(b"x")


def test_feed_does_not_allocate_a_payload_from_an_untrusted_header() -> None:
    decoder = FrameDecoder(max_frame_bytes=8)

    with pytest.raises(FrameError, match="exceeds"):
        decoder.feed(b"\xff\xff\xff\xff")


def test_finish_accepts_a_clean_stream_and_rejects_future_input() -> None:
    decoder = FrameDecoder()
    decoder.finish()

    with pytest.raises(FrameError, match="has ended"):
        decoder.feed(b"")


@pytest.mark.parametrize(
    "partial_frame",
    [b"\x00", b"\x00\x00\x00", b"\x00\x00\x00\x03a", b"\x00\x00\x00\x03ab"],
)
def test_finish_rejects_truncated_header_or_payload_and_stays_failed(
    partial_frame: bytes,
) -> None:
    decoder = FrameDecoder()
    assert decoder.feed(partial_frame) == []

    with pytest.raises(FrameError, match="Truncated frame"):
        decoder.finish()
    with pytest.raises(FrameError, match="has failed"):
        decoder.feed(b"")


def test_finish_is_not_idempotent() -> None:
    decoder = FrameDecoder()
    decoder.finish()

    with pytest.raises(FrameError, match="has ended"):
        decoder.finish()
