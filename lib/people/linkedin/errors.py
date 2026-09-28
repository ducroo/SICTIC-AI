"""Shared classification for callers that can use partial acquisition evidence."""

from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind


def is_acquisition_unavailable(error: InfrastructureError) -> bool:
    """Whether LinkedIn/Apify acquisition is unavailable without invalidating evidence.

    This is a partial-output policy, not a claim that retrying will fix the error.
    Authentication and credit failures may require user action.
    """
    return error.provider in {"apify", "linkedin"} and error.kind in {
        InfrastructureErrorKind.AUTHENTICATION,
        InfrastructureErrorKind.PERMISSION_DENIED,
        InfrastructureErrorKind.RATE_LIMIT,
        InfrastructureErrorKind.TIMEOUT,
        InfrastructureErrorKind.SERVICE_UNAVAILABLE,
        InfrastructureErrorKind.RESOURCE_BUSY,
    }
