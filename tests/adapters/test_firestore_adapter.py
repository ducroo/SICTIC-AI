from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lib.adapters.firestore import FirestoreAdapter, FirestoreQueryHit  # pragma: allowlist secret


class _FakeSnap:
    def __init__(self, exists: bool, data: dict | None = None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return dict(self._data)


def test_firestore_query_maps_cosine_distance_to_score(monkeypatch):  # pragma: allowlist secret
    adapter = FirestoreAdapter.__new__(FirestoreAdapter)  # pragma: allowlist secret
    adapter.collection_name = "demo-model"
    adapter._chunks = MagicMock()
    adapter._meta = MagicMock()
    adapter.collection_exists = lambda: True  # type: ignore[method-assign]

    doc = SimpleNamespace(
        id="chunk-1",
        to_dict=lambda: {
            "document_name": "deck.pdf",
            "text": "hello",
            "vector_distance": 0.25,
            "embedding": [0.1, 0.2],
        },
    )
    nearest = MagicMock()
    nearest.get.return_value = [doc]
    adapter._chunks.find_nearest.return_value = nearest

    # Avoid importing google libs in the unit test path beyond Vector/DistanceMeasure.
    class _DistanceMeasure:
        COSINE = "COSINE"

    class _Vector(list):
        def __init__(self, values):
            super().__init__(values)

    monkeypatch.setitem(
        __import__("sys").modules,
        "google.cloud.firestore_v1.base_vector_query",  # pragma: allowlist secret
        SimpleNamespace(DistanceMeasure=_DistanceMeasure),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.cloud.firestore_v1.vector",  # pragma: allowlist secret
        SimpleNamespace(Vector=_Vector),
    )

    hits = adapter.query([0.1, 0.2], limit=3)
    assert len(hits) == 1
    assert isinstance(hits[0], FirestoreQueryHit)  # pragma: allowlist secret
    assert hits[0].id == "chunk-1"
    assert hits[0].score == pytest.approx(0.75)
    assert hits[0].payload["document_name"] == "deck.pdf"
    assert "embedding" not in hits[0].payload
    assert "vector_distance" not in hits[0].payload


def test_firestore_ensure_collection_registers_meta():  # pragma: allowlist secret
    adapter = FirestoreAdapter.__new__(FirestoreAdapter)  # pragma: allowlist secret
    adapter.collection_name = "demo-model"
    adapter._meta = MagicMock()
    adapter._meta.get.return_value = _FakeSnap(False)
    adapter.collection_points_count = lambda: 0  # type: ignore[method-assign]
    adapter._ensure_vector_index = lambda _size: None  # type: ignore[method-assign]

    adapter.ensure_collection(8)
    adapter._meta.set.assert_called_once_with(
        {"vector_size": 8, "backend": "firestore"}  # pragma: allowlist secret
    )


def test_index_covers_embedding_matches_dimension():
    from types import SimpleNamespace
    from lib.adapters.firestore import _index_covers_embedding  # pragma: allowlist secret

    index = SimpleNamespace(
        fields=[
            SimpleNamespace(
                field_path="embedding",
                vector_config=SimpleNamespace(dimension=1536),
            )
        ]
    )
    assert _index_covers_embedding(index, 1536) is True
    assert _index_covers_embedding(index, 2048) is False
    assert _index_covers_embedding(SimpleNamespace(fields=[]), 1536) is False


def test_ensure_collection_rejects_oversize_vectors():
    adapter = FirestoreAdapter.__new__(FirestoreAdapter)  # pragma: allowlist secret
    adapter._meta = MagicMock()
    with pytest.raises(RuntimeError, match="max dimension"):
        adapter.ensure_collection(3072)
