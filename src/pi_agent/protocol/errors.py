"""Stable failures raised while reading one remote protocol frame."""


class FrameError(ValueError):
    """A length-prefixed frame is malformed, incomplete, or exceeds its bound."""


class ProtocolValidationError(ValueError):
    """A protocol payload is invalid; messages are safe to expose to peers."""

    def __init__(self) -> None:
        super().__init__("Invalid protocol message.")
