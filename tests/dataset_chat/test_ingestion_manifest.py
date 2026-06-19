from __future__ import annotations

import pytest

from lib.adapters.docling import ConversionStatus, DocumentConversionResult
from lib.storage import LocalStorage
from lib.datasets import conversion, indexing, source
from lib.datasets.manifest import (
    CHUNKER_VERSION,
    PARSER_VERSION,
    IngestionManifest,
    content_hash,
)


async def _results(items):
    for item in items:
        yield item


def test_indexed_dataset_revision_is_stable_and_persisted(tmp_path):
    storage = LocalStorage(tmp_path)
    manifest = IngestionManifest(storage, "cache/datasets2md/example")
    manifest.documents = {
        "b.md": {
            "indexed_parsed_sha256": "b-sha",
            "indexed_chunker_version": "chunker",
            "indexed_embedding_model": "embedding",
        },
        "ignored.md": {"parsed_sha256": "not-indexed"},
        "a.md": {
            "indexed_parsed_sha256": "a-sha",
            "indexed_chunker_version": "chunker",
            "indexed_embedding_model": "embedding",
        },
    }

    revision = manifest.update_indexed_dataset_revision()
    manifest.save()

    loaded = IngestionManifest.load(storage, manifest.parsed_rel)
    assert loaded.indexed_dataset_revision == revision

    loaded.documents = dict(reversed(list(loaded.documents.items())))
    assert loaded.update_indexed_dataset_revision() == revision


@pytest.mark.asyncio
async def test_failed_conversion_preserves_stale_parse_and_retries(tmp_path, mocker):
    storage = LocalStorage(tmp_path)
    raw_rel = "datasets/example"
    parsed_rel = "cache/datasets2md/example"
    storage.write_bytes(f"{raw_rel}/report.pdf", b"new source")
    storage.write_text(f"{parsed_rel}/report.pdf.md", "old parsed")

    manifest = IngestionManifest(storage, parsed_rel)
    manifest.documents["report.pdf"] = {
        "source_sha256": content_hash(b"old source"),
        "source_mtime": 1.0,
        "parsed_sha256": content_hash("old parsed"),
        "parser_version": PARSER_VERSION,
    }
    manifest.save()
    mocker.patch.object(conversion, "get_storage", return_value=storage)

    failed_adapter = mocker.Mock()
    failed_adapter.extract_documents.return_value = _results(
        [
            DocumentConversionResult(
                filename="report.pdf",
                status=ConversionStatus.FAILED,
                error="OCR unavailable",
            )
        ]
    )
    mocker.patch.object(conversion, "DoclingAdapter", return_value=failed_adapter)

    first = await conversion.reconcile_conversions("example", raw_rel, parsed_rel)

    assert storage.read_text(f"{parsed_rel}/report.pdf.md") == "old parsed"
    assert first.failures[0].stage == "conversion"
    failed_state = IngestionManifest.load(storage, parsed_rel).documents["report.pdf"]
    assert failed_state["source_sha256"] == content_hash(b"old source")

    successful_adapter = mocker.Mock()
    successful_adapter.extract_documents.return_value = _results(
        [
            DocumentConversionResult(
                filename="report.pdf",
                status=ConversionStatus.SUCCESS,
                text="new parsed",
            )
        ]
    )
    mocker.patch.object(conversion, "DoclingAdapter", return_value=successful_adapter)

    second = await conversion.reconcile_conversions("example", raw_rel, parsed_rel)

    assert second.converted == 1
    assert storage.read_text(f"{parsed_rel}/report.pdf.md") == "new parsed"
    state = IngestionManifest.load(storage, parsed_rel).documents["report.pdf"]
    assert state["source_sha256"] == content_hash(b"new source")
    assert state["parsed_sha256"] == content_hash("new parsed")


@pytest.mark.asyncio
async def test_empty_conversion_is_ignored_cleans_stale_state_and_is_not_retried(
    tmp_path,
    mocker,
):
    storage = LocalStorage(tmp_path)
    raw_rel = "datasets/example"
    parsed_rel = "cache/datasets2md/example"
    storage.write_bytes(f"{raw_rel}/image-only.pdf", b"non-empty source")
    storage.write_text(f"{parsed_rel}/image-only.pdf.md", "stale parsed text")
    source_document = source.snapshot_source_files(storage, raw_rel)[0]

    manifest = IngestionManifest(storage, parsed_rel)
    manifest.documents["image-only.pdf"] = {
        "source_sha256": content_hash(b"old source"),
        "source_mtime": 1.0,
        "parsed_sha256": content_hash("stale parsed text"),
        "parser_version": PARSER_VERSION,
        "indexed_parsed_sha256": content_hash("stale parsed text"),
        "indexed_chunker_version": CHUNKER_VERSION,
        "indexed_embedding_model": "test-model",
    }
    manifest.save()
    mocker.patch.object(conversion, "get_storage", return_value=storage)

    adapter = mocker.Mock()
    adapter.extract_documents.return_value = _results(
        [
            DocumentConversionResult(
                filename="image-only.pdf",
                status=ConversionStatus.IGNORED_EMPTY,
                reason="no_extractable_text",
            )
        ]
    )
    mocker.patch.object(conversion, "DoclingAdapter", return_value=adapter)

    first = await conversion.reconcile_conversions("example", raw_rel, parsed_rel)
    second = await conversion.reconcile_conversions("example", raw_rel, parsed_rel)

    assert first.ignored == 1
    assert first.failures == []
    assert second.ignored == 0
    assert adapter.extract_documents.call_count == 1
    assert not storage.exists(f"{parsed_rel}/image-only.pdf.md")
    state = IngestionManifest.load(storage, parsed_rel).documents["image-only.pdf"]
    assert state == {
        "source_sha256": source_document.sha256,
        "source_mtime": source_document.mtime,
        "parser_version": PARSER_VERSION,
        "ignored_reason": "no_extractable_text",
    }


@pytest.mark.asyncio
async def test_ignored_conversion_removes_existing_qdrant_document(tmp_path, mocker):
    storage = LocalStorage(tmp_path)
    raw_rel = "datasets/example"
    parsed_rel = "cache/datasets2md/example"
    storage.write_bytes(f"{raw_rel}/image-only.pdf", b"non-empty source")
    source_document = source.snapshot_source_files(storage, raw_rel)[0]

    manifest = IngestionManifest(storage, parsed_rel)
    manifest.documents["image-only.pdf"] = {
        "source_sha256": source_document.sha256,
        "source_mtime": source_document.mtime,
        "parser_version": PARSER_VERSION,
        "ignored_reason": "no_extractable_text",
    }
    manifest.save()
    mocker.patch.object(indexing, "get_storage", return_value=storage)

    qdrant = mocker.Mock()
    qdrant.collection_exists.return_value = True
    qdrant.get_document_mtimes.return_value = {"image-only.pdf": source_document.mtime}
    mocker.patch.object(indexing, "QdrantAdapter", return_value=qdrant)

    embeddings = mocker.Mock()
    embeddings.model = "test-model"
    mocker.patch.object(indexing, "EmbeddingService", return_value=embeddings)

    result = await indexing.reconcile_index(
        "example",
        raw_rel,
        parsed_rel,
        sources=[source_document],
        manifest=manifest,
    )

    assert result.removed_qdrant == 1
    assert result.failures == []
    qdrant.delete_document.assert_called_once_with(
        "image-only.pdf",
        raise_on_error=True,
    )


@pytest.mark.asyncio
async def test_parsed_orphans_are_removed_without_qdrant(tmp_path, mocker):
    storage = LocalStorage(tmp_path)
    raw_rel = "datasets/example"
    parsed_rel = "cache/datasets2md/example"
    storage.mkdir(raw_rel)
    storage.write_text(f"{parsed_rel}/deleted.pdf.md", "obsolete")
    mocker.patch.object(conversion, "get_storage", return_value=storage)

    result = await conversion.reconcile_conversions("example", raw_rel, parsed_rel)

    assert result.removed_parsed == 1
    assert not storage.exists(f"{parsed_rel}/deleted.pdf.md")


@pytest.mark.asyncio
async def test_failed_index_does_not_advance_manifest_checkpoint(tmp_path, mocker):
    storage = LocalStorage(tmp_path)
    raw_rel = "datasets/example"
    parsed_rel = "cache/datasets2md/example"
    storage.write_text(f"{raw_rel}/report.md", "source")
    storage.write_text(f"{parsed_rel}/report.md", "parsed")
    source_document = source.snapshot_source_files(storage, raw_rel)[0]

    manifest = IngestionManifest(storage, parsed_rel)
    manifest.documents["report.md"] = {
        "source_sha256": source_document.sha256,
        "source_mtime": source_document.mtime,
        "parsed_sha256": content_hash("parsed"),
        "parser_version": PARSER_VERSION,
        "indexed_parsed_sha256": "old-index",
        "indexed_chunker_version": CHUNKER_VERSION,
        "indexed_embedding_model": "test-model",
    }
    old_revision = manifest.update_indexed_dataset_revision()
    manifest.save()
    mocker.patch.object(indexing, "get_storage", return_value=storage)

    qdrant = mocker.Mock()
    qdrant.collection_exists.return_value = True
    qdrant.get_document_mtimes.return_value = {"report.md": 0.0}
    qdrant.ensure_collection.return_value = None
    mocker.patch.object(indexing, "QdrantAdapter", return_value=qdrant)

    embeddings = mocker.Mock()
    embeddings.model = "test-model"
    embeddings.vector_size.return_value = 3
    mocker.patch.object(indexing, "EmbeddingService", return_value=embeddings)
    mocker.patch.object(
        indexing,
        "replace_document",
        side_effect=RuntimeError("partial upsert"),
    )

    result = await indexing.reconcile_index(
        "example",
        raw_rel,
        parsed_rel,
        sources=[source_document],
        manifest=manifest,
    )

    assert result.failures[0].stage == "index"
    loaded = IngestionManifest.load(storage, parsed_rel)
    state = loaded.documents["report.md"]
    assert state["indexed_parsed_sha256"] == "old-index"
    assert loaded.indexed_dataset_revision == old_revision
