"""Shared Qdrant collection migration and tenant-isolation tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from lib.infrastructure import qdrant as qdrant_module


def _collection_info(
    size: int = 4,
    *,
    sparse: bool = False,
    tenant_index: bool = False,
):
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors=SimpleNamespace(size=size),
                sparse_vectors={"bm25": object()} if sparse else {},
            )
        ),
        payload_schema={
            qdrant_module.DATASET_PAYLOAD_KEY: object()
        }
        if tenant_index
        else {},
    )


class FakeClient:
    def __init__(self, collections=None):
        self.collections = dict(collections or {})
        self.deleted_collections = []
        self.created_indexes = []
        self.upserts = []
        self.queries = []
        self.deletes = []
        self.dataset_counts = {}

    def get_collections(self):
        return SimpleNamespace(
            collections=[
                SimpleNamespace(name=name)
                for name in sorted(self.collections)
            ]
        )

    def get_collection(self, collection_name):
        return self.collections[collection_name]

    def create_collection(
        self,
        *,
        collection_name,
        vectors_config,
        sparse_vectors_config,
        **_kwargs,
    ):
        self.collections[collection_name] = _collection_info(
            vectors_config.size,
            sparse=qdrant_module.SPARSE_VECTOR_NAME in sparse_vectors_config,
        )
        return True

    def create_payload_index(self, *, collection_name, field_name, **_kwargs):
        self.created_indexes.append((collection_name, field_name))
        self.collections[collection_name].payload_schema[field_name] = object()

    def delete_collection(self, collection_name):
        self.deleted_collections.append(collection_name)
        self.collections.pop(collection_name, None)

    def count(self, collection_name, count_filter=None, **_kwargs):
        if count_filter is None:
            return SimpleNamespace(count=sum(self.dataset_counts.values()))
        dataset = count_filter.must[0].match.value
        return SimpleNamespace(count=self.dataset_counts.get(dataset, 0))

    def upsert(self, *, collection_name, points):
        self.upserts.append((collection_name, points))

    def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(points=[])

    def delete(self, **kwargs):
        self.deletes.append(kwargs)

    def facet(self, **_kwargs):
        return SimpleNamespace(
            hits=[SimpleNamespace(value=value) for value in self.dataset_counts]
        )


@pytest.fixture(autouse=True)
def clear_layout_cache():
    qdrant_module._checked_layouts.clear()
    yield
    qdrant_module._checked_layouts.clear()


def test_adapter_migrates_only_exact_known_legacy_collection(monkeypatch):
    legacy = "avientus-qwen3-embedding-8b"
    unrelated = "other-app-qwen3-embedding-8b"
    client = FakeClient(
        {
            legacy: _collection_info(4096),
            unrelated: _collection_info(4096),
        }
    )
    reset = []
    monkeypatch.setattr(qdrant_module, "QdrantClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        "lib.datasets.paths.list_all_dataset_names",
        lambda: ["avientus"],
    )
    monkeypatch.setattr(
        qdrant_module.QdrantAdapter,
        "_reset_dataset_index_state",
        staticmethod(reset.append),
    )

    adapter = qdrant_module.QdrantAdapter(
        "avientus",
        embeddings_model="ollama/qwen3-embedding:8b",
    )

    assert adapter.collection_name == "sictic-ai-datasets-qwen3-embedding-8b"
    assert client.deleted_collections == [legacy]
    assert unrelated in client.collections
    assert adapter.collection_name in client.collections
    assert reset == ["avientus"]
    assert client.created_indexes == [
        (adapter.collection_name, qdrant_module.DATASET_PAYLOAD_KEY)
    ]


def test_adapter_namespaces_ids_and_adds_dataset_payload():
    client = FakeClient()
    first = object.__new__(qdrant_module.QdrantAdapter)
    first.client = client
    first.dataset_slug = "avientus"
    first.collection_name = "sictic-ai-datasets-qwen3-embedding-8b"
    first._sparse_enabled = True
    second = object.__new__(qdrant_module.QdrantAdapter)
    second.client = client
    second.dataset_slug = "another-dataset"
    second.collection_name = first.collection_name
    second._sparse_enabled = True
    point = {
        "id": "same-chunk-id",
        "vector": [1.0],
        "payload": {"document_name": "report.pdf"},
    }

    first_ids = first.upsert_points([point])
    second_ids = second.upsert_points([point])

    assert first_ids.isdisjoint(second_ids)
    first_point = client.upserts[0][1][0]
    second_point = client.upserts[1][1][0]
    assert first_point.payload[qdrant_module.DATASET_PAYLOAD_KEY] == "avientus"
    assert (
        second_point.payload[qdrant_module.DATASET_PAYLOAD_KEY]
        == "another-dataset"
    )


def test_queries_and_dataset_deletion_are_tenant_scoped():
    collection = "sictic-ai-datasets-qwen3-embedding-8b"
    client = FakeClient({collection: _collection_info(sparse=True, tenant_index=True)})
    client.dataset_counts = {"avientus": 2, "other": 3}
    adapter = object.__new__(qdrant_module.QdrantAdapter)
    adapter.client = client
    adapter.dataset_slug = "avientus"
    adapter.collection_name = collection
    adapter._sparse_enabled = True

    adapter.query([1.0], limit=5)
    deleted = adapter.delete_dataset()

    query_filter = client.queries[0]["query_filter"]
    assert query_filter.must[0].match.value == "avientus"
    assert deleted is True
    delete_filter = client.deletes[0]["points_selector"]
    assert delete_filter.must[0].match.value == "avientus"


def test_temporary_legacy_migration_has_not_expired():
    assert date.today() < qdrant_module.LEGACY_MIGRATION_REMOVE_AFTER, (
        "Remove or explicitly extend the temporary automatic Qdrant legacy "
        "migration after checking remaining installations."
    )
