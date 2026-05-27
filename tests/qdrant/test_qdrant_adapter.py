import pytest
import os
import uuid
import hashlib
from unittest.mock import patch, MagicMock
from lib.adapters.qdrant import QdrantAdapter, Chunker
from skills.dataset_chat.core.models import Chunk

@pytest.fixture
def mock_env(monkeypatch):
    """Mock the environment variables required by QdrantAdapter."""
    monkeypatch.setenv("DEFAULT_EMBEDDINGS", "ollama/test-embedding:8b")
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
