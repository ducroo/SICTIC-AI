from types import SimpleNamespace
import httpx
import pytest
from apify_client.errors import ApifyApiError
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind

from lib.infrastructure.apify import ApifyAdapter


@pytest.mark.parametrize("code,error_type,kind", [
    (403, "concurrent-runs-limit-exceeded", InfrastructureErrorKind.RESOURCE_BUSY),
    (403, "monthly-usage-limit-exceeded", InfrastructureErrorKind.PERMISSION_DENIED),
    (401, "invalid-token", InfrastructureErrorKind.AUTHENTICATION),
    (429, "rate-limit-exceeded", InfrastructureErrorKind.RATE_LIMIT),
    (503, "service-unavailable", InfrastructureErrorKind.SERVICE_UNAVAILABLE),
    (400, "invalid-input", InfrastructureErrorKind.INVALID_RESPONSE),
])
@pytest.mark.parametrize("operation", ["run_actor", "start_actor"])
def test_actor_failures_are_structured(mocker, code, error_type, kind, operation):
    error = ApifyApiError(httpx.Response(code, json={"error": {"type": error_type, "message": "Provider rejected launch"}}), 1)
    adapter = ApifyAdapter.__new__(ApifyAdapter)
    adapter.client = mocker.Mock()
    adapter.client.actor.return_value.call.side_effect = error
    adapter.client.actor.return_value.start.side_effect = error
    with pytest.raises(InfrastructureError) as caught:
        getattr(adapter, operation)("actor/id", {})
    assert caught.value.kind == kind
    assert caught.value.provider == "apify"
    assert caught.value.operation == operation
    assert caught.value.__cause__ is error


def test_apify_does_not_classify_programming_errors_as_service_failures(mocker):
    adapter = ApifyAdapter.__new__(ApifyAdapter)
    adapter.client = mocker.Mock()
    adapter.client.actor.side_effect = TypeError("Programming error")
    with pytest.raises(TypeError):
        adapter.run_actor("actor/id", {})


class _FakeDataset:
    def __init__(self, items):
        self.items = items

    def iterate_items(self):
        return iter(self.items)


class _FakeActor:
    def __init__(self, run):
        self.run = run
        self.input = None

    def call(self, *, run_input):
        self.input = run_input
        return self.run


class _FakeClient:
    def __init__(self, run, items):
        self.actor_client = _FakeActor(run)
        self.items = items
        self.dataset_id = None

    def actor(self, _actor_id):
        return self.actor_client

    def dataset(self, dataset_id):
        self.dataset_id = dataset_id
        return _FakeDataset(self.items)


def test_run_actor_accepts_object_run_result():
    adapter = ApifyAdapter.__new__(ApifyAdapter)
    adapter.client = _FakeClient(
        SimpleNamespace(default_dataset_id="dataset-123"),
        [{"title": "result"}],
    )

    results = adapter.run_actor("actor/id", {"query": "x"})

    assert results == [{"title": "result"}]
    assert adapter.client.dataset_id == "dataset-123"


def test_run_actor_accepts_dict_run_result():
    adapter = ApifyAdapter.__new__(ApifyAdapter)
    adapter.client = _FakeClient(
        {"defaultDatasetId": "dataset-456"},
        [{"title": "result"}],
    )

    results = adapter.run_actor("actor/id", {"query": "x"})

    assert results == [{"title": "result"}]
    assert adapter.client.dataset_id == "dataset-456"
