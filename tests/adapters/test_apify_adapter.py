from types import SimpleNamespace

from lib.adapters.apify import ApifyAdapter


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
