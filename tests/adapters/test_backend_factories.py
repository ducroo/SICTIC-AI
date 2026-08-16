from __future__ import annotations

import pytest

from lib.adapters import document_parser, vector_store
from lib.adapters.docling import DoclingAdapter
from lib.adapters.llamaparse import LlamaParseAdapter


def test_document_parser_defaults_to_docling(monkeypatch):
    monkeypatch.delenv("DOCUMENT_PARSER", raising=False)
    assert document_parser.document_parser_backend() == "docling"
    assert isinstance(document_parser.get_document_parser(), DoclingAdapter)


def test_document_parser_selects_llamaparse(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PARSER", "llamaparse")
    assert document_parser.document_parser_backend() == "llamaparse"
    assert isinstance(document_parser.get_document_parser(), LlamaParseAdapter)


def test_document_parser_rejects_unknown(monkeypatch):
    monkeypatch.setenv("DOCUMENT_PARSER", "magic")
    with pytest.raises(ValueError, match="Unsupported DOCUMENT_PARSER"):
        document_parser.document_parser_backend()


def test_vector_store_defaults_to_qdrant(monkeypatch):
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    assert vector_store.vector_store_backend() == "qdrant"


def test_vector_store_selects_firestore(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "firestore")
    assert vector_store.vector_store_backend() == "firestore"


def test_vector_store_rejects_unknown(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "pinecone")
    with pytest.raises(ValueError, match="Unsupported VECTOR_STORE"):
        vector_store.vector_store_backend()
