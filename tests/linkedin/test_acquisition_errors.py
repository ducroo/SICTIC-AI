import pytest

from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.people.linkedin.errors import is_acquisition_unavailable


@pytest.mark.parametrize("provider", ["linkedin", "apify", "qdrant"])
@pytest.mark.parametrize("kind", list(InfrastructureErrorKind))
def test_partial_acquisition_policy(provider, kind):
    error = InfrastructureError("failure", provider=provider, operation="test", kind=kind)
    assert is_acquisition_unavailable(error) == (
        provider in {"linkedin", "apify"} and kind in {
            InfrastructureErrorKind.AUTHENTICATION, InfrastructureErrorKind.PERMISSION_DENIED,
            InfrastructureErrorKind.RATE_LIMIT, InfrastructureErrorKind.TIMEOUT,
            InfrastructureErrorKind.SERVICE_UNAVAILABLE, InfrastructureErrorKind.RESOURCE_BUSY,
        }
    )
