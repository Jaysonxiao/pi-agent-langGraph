"""Safe failures exposed by the remote protocol client."""

from pi_agent.protocol.messages import ProtocolError


class ClientDisconnectedError(ConnectionError):
    """The byte stream closed before a request received a response."""


class ClientProtocolError(ClientDisconnectedError):
    """The peer violated the negotiated client protocol."""


class RequestOutcomeUnknownError(ClientDisconnectedError):
    """A request may have reached the server, but its result was not observed."""


class ServerRejectedError(RuntimeError):
    """The server returned a safe protocol-level command failure."""

    def __init__(self, error: ProtocolError) -> None:
        super().__init__(error.message)
        self.code = error.code
        self.safe_message = error.message


class UnsupportedProtocolVersionError(ClientProtocolError):
    """The server rejected the client's hello version."""
