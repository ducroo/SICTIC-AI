from __future__ import annotations

import pytest

from lib.infrastructure import document_parser, vector_store
from lib.infrastructure.document_conversion.converter import _backend
from lib.infrastructure.document_parser import SAAS_DOCUMENT_PARSER
from lib.infrastructure.vector_store import SAAS_VECTOR_STORE


def test_document_parser_defaults_to_docling(monkeypatch):
    monkeypatch.delenv("DOCUMENT_PARSER", raising=False)
    monkeypatch.delenv("DOCUMENT_CONVERTER", raising=False)
    assert document_parser.document_parser_backend() == "docling"
    assert document_parser.document_converter_provider() == "docling_stack"
    assert _backend("docling_stack").__module__.endswith("docling_stack.converter")


def test_document_parser_selects_llamaparse(monkeypatch):  # pragma: allowlist secret
    monkeypatch.setenv("DOCUMENT_PARSER", SAAS_DOCUMENT_PARSER)
    monkeypatch.setenv("DOCUMENT_CONVERTER", "docling_stack")
    assert document_parser.document_parser_backend() == SAAS_DOCUMENT_PARSER
    assert document_parser.document_converter_provider() == SAAS_DOCUMENT_PARSER
    assert _backend(SAAS_DOCUMENT_PARSER).__module__.endswith("llamaparse.adapter")  # pragma: allowlist secret


def test_document_converter_env_selects_llamaparse(monkeypatch):  # pragma: allowlist secret
    monkeypatch.delenv("DOCUMENT_PARSER", raising=False)
    monkeypatch.setenv("DOCUMENT_CONVERTER", SAAS_DOCUMENT_PARSER)
    assert document_parser.document_parser_backend() == SAAS_DOCUMENT_PARSER
    assert document_parser.document_converter_provider() == SAAS_DOCUMENT_PARSER


def test_document_parser_rejects_unknown(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PARSER", "magic")
    with pytest.raises(ValueError, match="Unsupported DOCUMENT_PARSER"):
        document_parser.document_parser_backend()


def test_vector_store_defaults_to_qdrant(monkeypatch):
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    assert vector_store.vector_store_backend() == "qdrant"


def test_vector_store_selects_firestore(monkeypatch):  # pragma: allowlist secret
    monkeypatch.setenv("VECTOR_STORE", SAAS_VECTOR_STORE)
    assert vector_store.vector_store_backend() == SAAS_VECTOR_STORE


def test_vector_store_rejects_unknown(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "pinecone")
    with pytest.raises(ValueError, match="Unsupported VECTOR_STORE"):
        vector_store.vector_store_backend()


def test_firestore_embedding_dimensions_default_and_bounds(monkeypatch):  # pragma: allowlist secret
    from lib.infrastructure.vector_store import firestore_embedding_dimensions  # pragma: allowlist secret

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
    from lib.datasets.embeddings import _embedding_call_kwargs
    from lib.model_config import ModelEndpoint

    monkeypatch.setenv("VECTOR_STORE", SAAS_VECTOR_STORE)
    monkeypatch.delenv("FIRESTORE_EMBEDDING_DIMENSIONS", raising=False)  # pragma: allowlist secret
    endpoint = ModelEndpoint(model="openai/test-embedding", api_key="embed-key")
    kwargs = _embedding_call_kwargs(endpoint)
    assert kwargs["dimensions"] == 1536
    monkeypatch.setenv("VECTOR_STORE", "qdrant")
    kwargs = _embedding_call_kwargs(endpoint)
    assert "dimensions" not in kwargs
