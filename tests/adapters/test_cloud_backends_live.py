from __future__ import annotations

import os

import pytest
from dotenv import dotenv_values

from lib.adapters.document_parser import document_parser_backend
from lib.adapters.llamaparse import LlamaParseAdapter  # pragma: allowlist secret
from lib.adapters.vector_store import vector_store_backend
from lib.datasets.embeddings import EmbeddingService, _vector_size_cache
from lib.datasets.search import dataset_search
from lib.ephemeral_dataset import prepare_ephemeral_dataset

pytestmark = pytest.mark.live

_MINIMAL_PDF = b"""%PDF-1.1
1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj
2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj
3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj
4 0 obj<< /Length 68 >>stream
BT /F1 24 Tf 72 720 Td (SICTIC cloud smoke test) Tj ET
endstream
endobj
5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj
trailer<< /Root 1 0 R >>
%%EOF
"""


def _secrets_present() -> bool:
    return bool(
        os.environ.get("LLAMA_CLOUD_API_KEY")
        and (
            os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
    )


def _restore_cloud_embedding_env(monkeypatch) -> None:
    values = dotenv_values("/workspace/.env")
    for key in (
        "EMBEDDING_MODEL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_BASE_URL",
        "LLM_MODEL",
        "LLM_API_KEY",
    ):
        value = values.get(key)
        if value:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("DOCUMENT_PARSER", "llamaparse")  # pragma: allowlist secret
    monkeypatch.setenv("VECTOR_STORE", "firestore")  # pragma: allowlist secret
    monkeypatch.setenv("FIRESTORE_EMBEDDING_DIMENSIONS", "1536")  # pragma: allowlist secret
    _vector_size_cache.clear()


@pytest.mark.asyncio
async def test_live_firestore_markdown_search(tmp_path, monkeypatch):  # pragma: allowlist secret
    if not _secrets_present():
        pytest.skip("Firebase / LlamaCloud secrets are not present")

    _restore_cloud_embedding_env(monkeypatch)
    assert document_parser_backend() == "llamaparse"  # pragma: allowlist secret
    assert vector_store_backend() == "firestore"  # pragma: allowlist secret
    assert EmbeddingService().vector_size() == 1536

    notes = tmp_path / "cloud-smoke.md"
    notes.write_text(
        "# Acme Robotics\n\nAcme Robotics builds warehouse picking arms in Zurich.\n",
        encoding="utf-8",
    )
    dataset = await prepare_ephemeral_dataset(
        [str(notes)],
        temp_name="cloud-smoke",
    )
    hits = await dataset_search(
        dataset,
        "What does Acme Robotics build?",
        max_chunks=3,
        raise_on_error=True,
    )
    assert hits
    blob = " ".join(hit.text for hit in hits).lower()
    assert "acme" in blob or "warehouse" in blob or "picking" in blob


@pytest.mark.asyncio
async def test_live_llamaparse_pdf(tmp_path, monkeypatch):  # pragma: allowlist secret
    if not os.environ.get("LLAMA_CLOUD_API_KEY"):
        pytest.skip("LLAMA_CLOUD_API_KEY is not present")

    _restore_cloud_embedding_env(monkeypatch)
    pdf = tmp_path / "cloud-smoke.pdf"
    pdf.write_bytes(_MINIMAL_PDF)
    adapter = LlamaParseAdapter(concurrency_limit=1)  # pragma: allowlist secret
    results = [
        item
        async for item in adapter.extract_documents(
            [{"filename": pdf.name, "local_path": pdf}]
        )
    ]
    assert len(results) == 1
    assert not results[0].error
    assert results[0].text.strip()
