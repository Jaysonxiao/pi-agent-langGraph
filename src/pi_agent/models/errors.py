"""Safe provider errors for the M8.2 model boundary."""

from typing import Literal

ProviderErrorCode = Literal["provider_call_failed", "invalid_response", "client_creation_failed"]


class ModelProviderError(RuntimeError):
    """Stable error that never includes provider exception text or credentials."""

    def __init__(
        self, code: ProviderErrorCode, exception_type: str, *, status_code: int | None = None
    ) -> None:
        self.code = code
        self.exception_type = exception_type
        self.status_code = status_code
        super().__init__(f"Model provider request failed ({code}).")


class ModelFactoryError(RuntimeError):
    """Safe construction error at the provider factory boundary."""

    def __init__(self, message: str = "Model provider client could not be created.") -> None:
        super().__init__(message)
