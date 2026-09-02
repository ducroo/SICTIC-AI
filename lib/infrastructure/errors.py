"""Provider-independent infrastructure failures."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class InfrastructureErrorKind(StrEnum):
    """Stable categories used for recovery decisions and diagnostics."""

    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INVALID_RESPONSE = "invalid_response"
    DATA_INTEGRITY = "data_integrity"
    RESOURCE_BUSY = "resource_busy"


_DEFAULT_RECOVERABILITY: Final[dict[InfrastructureErrorKind, bool]] = {
    InfrastructureErrorKind.CONFIGURATION: False,
    InfrastructureErrorKind.AUTHENTICATION: False,
    InfrastructureErrorKind.PERMISSION_DENIED: False,
    InfrastructureErrorKind.RATE_LIMIT: True,
    InfrastructureErrorKind.TIMEOUT: True,
    InfrastructureErrorKind.SERVICE_UNAVAILABLE: True,
    InfrastructureErrorKind.INVALID_RESPONSE: False,
    InfrastructureErrorKind.DATA_INTEGRITY: False,
    InfrastructureErrorKind.RESOURCE_BUSY: True,
}


class InfrastructureError(RuntimeError):
    """Failure exposed by an infrastructure boundary.

    Chain the provider exception with ``raise ... from error`` so its original
    traceback remains available without becoming part of the public contract.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: InfrastructureErrorKind,
        provider: str,
        operation: str,
        recoverable: bool | None = None,
    ) -> None:
        self.kind = InfrastructureErrorKind(kind)
        self.provider = provider
        self.operation = operation
        self.recoverable = (
            _DEFAULT_RECOVERABILITY[self.kind]
            if recoverable is None
            else recoverable
        )
        super().__init__(f"{provider}.{operation}: {message}")
