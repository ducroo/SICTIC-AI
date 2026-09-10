from types import SimpleNamespace
from unittest.mock import MagicMock

from lib.infrastructure.qdrant import QdrantAdapter


def test_adapter_creates_collection_from_explicit_vector_size(mock_env, mocker):
    client_class = mocker.patch("lib.infrastructure.qdrant.QdrantClient")
    client = client_class.return_value
    client.get_collections.return_value.collections = []

    adapter = QdrantAdapter("test-dataset", vector_size=4096)

    assert adapter.collection_name == "sictic-ai-datasets-test-embedding-8b"
    create_kwargs = client.create_collection.call_args.kwargs
    assert create_kwargs["collection_name"] == adapter.collection_name
    assert create_kwargs["vectors_config"].size == 4096


def test_get_document_mtimes_scrolls_all_pages_and_keeps_newest_timestamp():
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    adapter.dataset_slug = "test-dataset"
    adapter.client.scroll.side_effect = [
        (
            [
                SimpleNamespace(
                    payload={
                        "document_name": "track-record/patrick.md",
                        "last_modified": 1.0,
                    }
                )
            ],
            "next-page",
        ),
        (
            [
                SimpleNamespace(
                    payload={
                        "document_name": "track-record/patrick.md",
                        "last_modified": 2.0,
                    }
                ),
                SimpleNamespace(
                    payload={
                        "document_name": "resume.pdf",
                        "last_modified": 3.0,
                    }
                ),
            ],
            None,
        ),
    ]

    assert adapter.get_document_mtimes() == {
        "track-record/patrick.md": 2.0,
        "resume.pdf": 3.0,
    }
    assert adapter.client.scroll.call_count == 2


def test_upsert_points_translates_records_to_qdrant_points():
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    adapter.dataset_slug = "test-dataset"

    adapter.upsert_points(
        [
            {
                "id": "b6dd4af9-8a10-4666-b9ae-a8e3e54e16ba",
                "vector": [1.0, 2.0],
                "payload": {"document_name": "document.md", "text": "content"},
            }
        ]
    )

    points = adapter.client.upsert.call_args.kwargs["points"]
    assert len(points) == 1
    assert points[0].vector == [1.0, 2.0]
    assert points[0].payload["document_name"] == "document.md"
    assert points[0].payload["dataset_slug"] == "test-dataset"


def test_query_passes_vector_and_limit_to_qdrant():
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    adapter.dataset_slug = "test-dataset"
    adapter.collection_exists = lambda: True
    expected = [SimpleNamespace(id="one")]
    adapter.client.query_points.return_value = SimpleNamespace(points=expected)

    result = adapter.query([1.0], limit=25)

    assert result == expected
    query_kwargs = adapter.client.query_points.call_args.kwargs
    assert query_kwargs["collection_name"] == "test-collection"
    assert query_kwargs["query"] == [1.0]
    assert query_kwargs["limit"] == 25
    assert query_kwargs["with_payload"] is True
    assert query_kwargs["query_filter"].must[0].match.value == "test-dataset"


def _query_adapter(client, *, exists: bool) -> QdrantAdapter:
    adapter = object.__new__(QdrantAdapter)
    adapter.client = client
    adapter.collection_name = "proud-technology-test-embedding"
    adapter.dataset_slug = "proud-technology"
    adapter.collection_exists = lambda: exists
    return adapter


def test_query_returns_zero_chunks_and_warns_when_collection_is_missing(mocker):
    client = mocker.Mock()
    adapter = _query_adapter(client, exists=False)
    warning = mocker.patch("lib.infrastructure.qdrant.logger.warning")

    assert adapter.query([1.0], limit=25) == []

    client.query_points.assert_not_called()
    warning.assert_called_once_with(
        "Qdrant collection %s does not exist; returning zero chunks.",
        adapter.collection_name,
    )


def test_query_returns_zero_chunks_and_warns_when_collection_is_empty(mocker):
    client = mocker.Mock()
    client.query_points.return_value = SimpleNamespace(points=[])
    adapter = _query_adapter(client, exists=True)
    warning = mocker.patch("lib.infrastructure.qdrant.logger.warning")

    assert adapter.query([1.0], limit=25) == []

    warning.assert_called_once_with(
        "Qdrant collection %s exists but the query returned zero chunks.",
        adapter.collection_name,
    )


def test_query_propagates_qdrant_failures(mocker):
    client = mocker.Mock()
    client.query_points.side_effect = RuntimeError("Qdrant unavailable")
    adapter = _query_adapter(client, exists=True)

    try:
        adapter.query([1.0], limit=25)
    except RuntimeError as error:
        assert str(error) == "Qdrant unavailable"
    else:
        raise AssertionError("Expected the Qdrant failure to propagate")
