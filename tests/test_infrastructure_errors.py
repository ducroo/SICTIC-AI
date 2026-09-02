from __future__ import annotations

import pytest

from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)


@pytest.mark.parametrize(
    ("kind", "recoverable"),
    [
        (InfrastructureErrorKind.CONFIGURATION, False),
        (InfrastructureErrorKind.AUTHENTICATION, False),
        (InfrastructureErrorKind.PERMISSION_DENIED, False),
        (InfrastructureErrorKind.RATE_LIMIT, True),
        (InfrastructureErrorKind.TIMEOUT, True),
        (InfrastructureErrorKind.SERVICE_UNAVAILABLE, True),
        (InfrastructureErrorKind.INVALID_RESPONSE, False),
        (InfrastructureErrorKind.DATA_INTEGRITY, False),
        (InfrastructureErrorKind.RESOURCE_BUSY, True),
    ],
)
def test_default_recoverability(kind, recoverable):
    error = InfrastructureError(
        "failed",
        kind=kind,
        provider="example",
        operation="read",
    )

    assert error.recoverable is recoverable


def test_error_exposes_stable_context():
    error = InfrastructureError(
        "response could not be parsed",
        kind=InfrastructureErrorKind.INVALID_RESPONSE,
        provider="dealum",
        operation="retrieve_dossier",
    )

    assert isinstance(error, RuntimeError)
    assert error.kind is InfrastructureErrorKind.INVALID_RESPONSE
    assert error.provider == "dealum"
    assert error.operation == "retrieve_dossier"
    assert str(error) == (
        "dealum.retrieve_dossier: response could not be parsed"
    )


def test_operation_can_override_default_recoverability():
    error = InfrastructureError(
        "provider returned an incomplete transient response",
        kind=InfrastructureErrorKind.INVALID_RESPONSE,
        provider="example",
        operation="generate",
        recoverable=True,
    )

    assert error.recoverable is True


def test_original_exception_is_preserved_by_standard_chaining():
    cause = TimeoutError("socket timeout")

    try:
        raise InfrastructureError(
            "provider timed out",
            kind=InfrastructureErrorKind.TIMEOUT,
            provider="example",
            operation="read",
        ) from cause
    except InfrastructureError as error:
        assert error.__cause__ is cause
