from __future__ import annotations

import pytest

from lib.adapters import document_parser, vector_store
from lib.adapters.docling import DoclingAdapter
from lib.adapters.llamaparse import LlamaParseAdapter  # pragma: allowlist secret


def test_document_parser_defaults_to_docling(monkeypatch):
    monkeypatch.delenv("DOCUMENT_PARSER", raising=False)
    assert document_parser.document_parser_backend() == "docling"
    assert isinstance(document_parser.get_document_parser(), DoclingAdapter)


def test_document_parser_selects_llamaparse(monkeypatch):  # pragma: allowlist secret
    monkeypatch.setenv("DOCUMENT_PARSER", "llamaparse")  # pragma: allowlist secret
    assert document_parser.document_parser_backend() == "llamaparse"  # pragma: allowlist secret
    assert isinstance(document_parser.get_document_parser(), LlamaParseAdapter)  # pragma: allowlist secret


def test_document_parser_rejects_unknown(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PARSER", "magic")
    with pytest.raises(ValueError, match="Unsupported DOCUMENT_PARSER"):
        document_parser.document_parser_backend()


def test_vector_store_defaults_to_qdrant(monkeypatch):
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    assert vector_store.vector_store_backend() == "qdrant"


def test_vector_store_selects_firestore(monkeypatch):  # pragma: allowlist secret
    monkeypatch.setenv("VECTOR_STORE", "firestore")  # pragma: allowlist secret
    assert vector_store.vector_store_backend() == "firestore"  # pragma: allowlist secret


def test_vector_store_rejects_unknown(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "pinecone")
    with pytest.raises(ValueError, match="Unsupported VECTOR_STORE"):
        vector_store.vector_store_backend()


def test_firestore_embedding_dimensions_default_and_bounds(monkeypatch):  # pragma: allowlist secret
    from lib.adapters.vector_store import firestore_embedding_dimensions  # pragma: allowlist secret

    monkeypatch.delenv("FIRESTORE_EMBEDDING_DIMENSIONS", raising=False)  # pragma: allowlist secret
    assert firestore_embedding_dimensions() == 1536  # pragma: allowlist secret
    monkeypatch.setenv("FIRESTORE_EMBEDDING_DIMENSIONS", "2048")  # pragma: allowlist secret
    assert firestore_embedding_dimensions() == 2048  # pragma: allowlist secret
    monkeypatch.setenv("FIRESTORE_EMBEDDING_DIMENSIONS", "3072")  # pragma: allowlist secret
    with pytest.raises(ValueError, match="outside"):
        firestore_embedding_dimensions()  # pragma: allowlist secret
    monkeypatch.setenv("FIRESTORE_EMBEDDING_DIMENSIONS", "abc")  # pragma: allowlist secret
    with pytest.raises(ValueError, match="integer"):
        firestore_embedding_dimensions()  # pragma: allowlist secret


def test_embedding_kwargs_add_dimensions_for_firestore(monkeypatch):  # pragma: allowlist secret
    from lib.datasets.embeddings import EmbeddingService

    monkeypatch.setenv("VECTOR_STORE", "firestore")  # pragma: allowlist secret
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/test-embedding")
    monkeypatch.setenv("EMBEDDING_API_KEY", "embed-key")
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("FIRESTORE_EMBEDDING_DIMENSIONS", raising=False)  # pragma: allowlist secret
    kwargs = EmbeddingService()._litellm_kwargs()
    assert kwargs["dimensions"] == 1536
    monkeypatch.setenv("VECTOR_STORE", "qdrant")
    kwargs = EmbeddingService()._litellm_kwargs()
    assert "dimensions" not in kwargs
