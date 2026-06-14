import pytest
import asyncio
import os
import uuid
import hashlib
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from lib.adapters.qdrant import QdrantAdapter, Chunker
from skills.dataset_chat.core.models import Chunk

@pytest.fixture
def mock_env(monkeypatch):
    """Mock the environment variables required by QdrantAdapter."""
    monkeypatch.setenv("EMBEDDING_MODEL", "ollama/test-embedding:8b")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    # Suppress console warnings for tests
    monkeypatch.setenv("GRPC_VERBOSITY", "ERROR")
    monkeypatch.setenv("GRPC_TRACE", "")

@pytest.fixture
def mock_qdrant_client(mocker):
    """Mock the QdrantClient to prevent actual DB calls during fast tests."""
    mock_client_class = mocker.patch("lib.adapters.qdrant.QdrantClient")
    mock_client_instance = mock_client_class.return_value
    
    # Mock get_collections to return an empty list initially (collection doesn't exist)
    mock_collections_response = MagicMock()
    mock_collections_response.collections = []
    mock_client_instance.get_collections.return_value = mock_collections_response
    
    return mock_client_instance

@pytest.fixture
def mock_litellm_embedding(mocker):
    """Mock the synchronous litellm.embedding call used during initialization."""
    # Since litellm is imported inside the __init__ block, we mock it globally
    mock_embedding = mocker.patch("litellm.embedding")
    
    # Return a dummy vector of size 4096 to simulate qwen3/llama3 embedding
    mock_response = MagicMock()
    mock_response.data = [{"embedding": [0.1] * 4096}]
    mock_embedding.return_value = mock_response
    
    return mock_embedding

def test_qdrant_adapter_dynamic_dimension(mock_env, mock_qdrant_client, mock_litellm_embedding):
    """
    Test that initializing a QdrantAdapter for a new collection dynamically 
    determines the vector dimension size and passes it to create_collection.
    """
    # 1. Initialize the adapter
    adapter = QdrantAdapter("test-dataset")
    
    # 2. Verify collection name was slugified correctly with the model name
    assert adapter.collection_name == "test-dataset-test-embedding-8b"
    
    # 3. Verify the litellm sync API was called with the dummy "test" string
    mock_litellm_embedding.assert_called_once()
    kwargs = mock_litellm_embedding.call_args.kwargs
    assert kwargs["model"] == "ollama/test-embedding:8b"
    assert kwargs["input"] == ["test"]
    assert kwargs["api_base"] == "http://localhost:11434"
    
    # 4. Verify create_collection was called with the dynamically detected size (4096)
    mock_qdrant_client.create_collection.assert_called_once()
    create_kwargs = mock_qdrant_client.create_collection.call_args.kwargs
    assert create_kwargs["collection_name"] == "test-dataset-test-embedding-8b"
    assert create_kwargs["vectors_config"].size == 4096

def test_chunker_split_markdown():
    """Test that the Chunker correctly splits markdown and generates UUIDs."""
    text = "This is a test document. " * 100  # Generate some length
    filename = "test_file.md"
    mod_time = 123456789.0
    
    chunks = Chunker.split_markdown(text, filename, mod_time)
    
    assert len(chunks) > 0
    first_chunk = chunks[0]
    
    assert first_chunk.document_name == filename
    assert first_chunk.last_modified == mod_time
    assert len(first_chunk.text) <= 1100  # 1000 chunk_size + 100 overlap max
    
    # Verify hash integrity
    expected_hash_str = f"{filename}_{first_chunk.text}"
    expected_hash = hashlib.md5(expected_hash_str.encode('utf-8')).hexdigest()
    expected_uuid = str(uuid.UUID(hex=expected_hash))
    assert first_chunk.chunk_id == expected_uuid


def test_get_document_mtimes_scrolls_all_pages_and_keeps_newest_timestamp():
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    adapter.client.scroll.side_effect = [
        (
            [
                SimpleNamespace(
                    payload={"document_name": "track-record/patrick.md", "last_modified": 1.0}
                )
            ],
            "next-page",
        ),
        (
            [
                SimpleNamespace(
                    payload={"document_name": "track-record/patrick.md", "last_modified": 2.0}
                ),
                SimpleNamespace(
                    payload={"document_name": "resume.pdf", "last_modified": 3.0}
                ),
            ],
            None,
        ),
    ]

    mtimes = adapter.get_document_mtimes()

    assert mtimes == {
        "track-record/patrick.md": 2.0,
        "resume.pdf": 3.0,
    }
    assert adapter.client.scroll.call_count == 2
    assert adapter.client.scroll.call_args_list[0].kwargs["offset"] is None
    assert adapter.client.scroll.call_args_list[1].kwargs["offset"] == "next-page"


@pytest.mark.asyncio
async def test_get_embedding_uses_services_gateway(mock_env, mocker):
    adapter = object.__new__(QdrantAdapter)
    request = mocker.patch(
        "lib.adapters.qdrant.gateway.request_embedding",
        return_value=SimpleNamespace(data=[{"embedding": [0.1, 0.2]}]),
    )

    vector = await adapter._get_embedding("chunk text")

    assert vector == [0.1, 0.2]
    request.assert_awaited_once()
    assert request.await_args.args[0]["input"] == ["chunk text"]


@pytest.mark.asyncio
async def test_upsert_embeds_chunks_concurrently_and_preserves_order(mocker):
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    active = 0
    max_active = 0

    async def fake_embedding(text):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [float(text)]

    mocker.patch.object(adapter, "_get_embedding", side_effect=fake_embedding)
    chunks = [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            document_name="document.md",
            page_number=1,
            last_modified=1.0,
            text=str(index),
        )
        for index in range(6)
    ]

    await adapter.upsert(chunks)

    assert max_active == 6
    points = adapter.client.upsert.call_args.kwargs["points"]
    assert [point.vector for point in points] == [
        [float(index)] for index in range(6)
    ]
    assert [point.payload["text"] for point in points] == [
        str(index) for index in range(6)
    ]


@pytest.mark.asyncio
async def test_upsert_does_not_write_partial_document_on_embedding_failure(mocker):
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"

    async def fake_embedding(text):
        if text == "bad":
            raise RuntimeError("embedding failed")
        await asyncio.sleep(0)
        return [1.0]

    mocker.patch.object(adapter, "_get_embedding", side_effect=fake_embedding)
    chunks = [
        Chunk(
            chunk_id=str(uuid.uuid4()),
            document_name="document.md",
            page_number=1,
            last_modified=1.0,
            text=text,
        )
        for text in ("good", "bad", "also-good")
    ]

    with pytest.raises(RuntimeError, match="embedding failed"):
        await adapter.upsert(chunks)

    adapter.client.upsert.assert_not_called()


def _query_result(chunk_id, score, text=None):
    return SimpleNamespace(
        id=chunk_id,
        score=score,
        payload={
            "chunk_id": chunk_id,
            "document_name": f"{chunk_id}.md",
            "page_number": 1,
            "last_modified": 1.0,
            "text": text or chunk_id,
        },
    )


@pytest.mark.asyncio
async def test_search_runs_queries_separately_and_merges_round_robin(mocker):
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    mocker.patch.object(
        adapter,
        "_get_embedding",
        side_effect=lambda query: {
            "technology": [1.0],
            "business": [2.0],
        }[query],
    )
    adapter.client.query_points.side_effect = [
        SimpleNamespace(
            points=[
                _query_result("tech-1", 0.99),
                _query_result("shared", 0.90),
                _query_result("tech-3", 0.80),
            ]
        ),
        SimpleNamespace(
            points=[
                _query_result("business-1", 0.98),
                _query_result("shared", 0.95),
                _query_result("business-3", 0.79),
            ]
        ),
    ]

    chunks = await adapter.search(
        ["technology", "business"],
        max_chunks=5,
    )

    assert [chunk.chunk_id for chunk in chunks] == [
        "tech-1",
        "business-1",
        "shared",
        "tech-3",
        "business-3",
    ]
    assert adapter._get_embedding.await_count == 2
    assert adapter.client.query_points.call_count == 2
    assert all(
        call.kwargs["limit"] == 5
        for call in adapter.client.query_points.call_args_list
    )


@pytest.mark.asyncio
async def test_search_returns_all_available_unique_chunks_up_to_max(mocker):
    adapter = object.__new__(QdrantAdapter)
    adapter.client = MagicMock()
    adapter.collection_name = "test-collection"
    mocker.patch.object(adapter, "_get_embedding", return_value=[1.0])
    adapter.client.query_points.return_value = SimpleNamespace(
        points=[
            _query_result("one", 0.9),
            _query_result("two", 0.1),
        ]
    )

    chunks = await adapter.search("query", max_chunks=25)

    assert [chunk.chunk_id for chunk in chunks] == ["one", "two"]
