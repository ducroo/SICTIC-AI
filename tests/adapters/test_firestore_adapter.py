from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lib.adapters.firestore import FirestoreAdapter, FirestoreQueryHit


class _FakeSnap:
    def __init__(self, exists: bool, data: dict | None = None):
        self.exists = exists
        self._data = data or {}

    def to_dict(self):
        return dict(self._data)


def test_firestore_query_maps_cosine_distance_to_score(monkeypatch):
    adapter = FirestoreAdapter.__new__(FirestoreAdapter)
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
        "google.cloud.firestore_v1.base_vector_query",
        SimpleNamespace(DistanceMeasure=_DistanceMeasure),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "google.cloud.firestore_v1.vector",
        SimpleNamespace(Vector=_Vector),
    )

    hits = adapter.query([0.1, 0.2], limit=3)
    assert len(hits) == 1
    assert isinstance(hits[0], FirestoreQueryHit)
    assert hits[0].id == "chunk-1"
    assert hits[0].score == pytest.approx(0.75)
    assert hits[0].payload["document_name"] == "deck.pdf"
    assert "embedding" not in hits[0].payload
    assert "vector_distance" not in hits[0].payload


def test_firestore_ensure_collection_registers_meta():
    adapter = FirestoreAdapter.__new__(FirestoreAdapter)
    adapter.collection_name = "demo-model"
    adapter._meta = MagicMock()
    adapter._meta.get.return_value = _FakeSnap(False)
    adapter.collection_points_count = lambda: 0  # type: ignore[method-assign]

    adapter.ensure_collection(8)
    adapter._meta.set.assert_called_once_with(
        {"vector_size": 8, "backend": "firestore"}
    )
