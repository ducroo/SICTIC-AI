from __future__ import annotations

from types import SimpleNamespace

import pytest

from lib.datasets import indexing, source
from lib.datasets.indexing import replace_document
from lib.datasets.manifest import (
    CHUNKER_VERSION,
    PARSER_VERSION,
    IngestionManifest,
    content_hash,
)
from lib.datasets.sparse import SPARSE_ENCODER_VERSION, token_id
from lib.storage import LocalStorage


class _Embeddings:
    model = "test-model"

    async def embed_many(self, texts):
        return [[1.0] for _ in texts]

    async def vector_size(self):
        return 1


def _chunk(chunk_id: str, text: str):
    return SimpleNamespace(
        chunk_id=chunk_id,
        text=text,
        model_dump=lambda: {"document_name": "report.pdf", "text": text},
    )


@pytest.mark.asyncio
async def test_replacement_omits_sparse_vectors_by_default():
    captured = {}
    qdrant = SimpleNamespace(
        get_document_point_ids=lambda _name: set(),
        upsert_points=lambda points: captured.setdefault("points", points),
        delete_point_ids=lambda _ids: None,
    )

    await replace_document(
        qdrant,
        _Embeddings(),
        "report.pdf",
        [_chunk("chunk-1", "patent assignment")],
    )

    assert "sparse" not in captured["points"][0]


@pytest.mark.asyncio
async def test_replacement_attaches_bm25_vectors_for_hybrid_collections():
    captured = {}
    qdrant = SimpleNamespace(
        get_document_point_ids=lambda _name: set(),
        upsert_points=lambda points: captured.setdefault("points", points),
        delete_point_ids=lambda _ids: None,
    )

    await replace_document(
        qdrant,
        _Embeddings(),
        "report.pdf",
        [_chunk("chunk-1", "patent assignment")],
        with_sparse=True,
    )

    sparse = captured["points"][0]["sparse"]
    assert token_id("patent") in sparse.indices
    assert token_id("assignment") in sparse.indices


def _indexed_dataset(tmp_path, mocker, *, sparse_state: str | None):
    storage = LocalStorage(tmp_path)
    raw_rel = "datasets/example"
    parsed_rel = "cache/datasets2md/example"
    storage.write_text(f"{raw_rel}/report.md", "parsed body")
    storage.write_text(f"{parsed_rel}/report.md", "parsed body")
    source_document = source.snapshot_source_files(storage, raw_rel)[0]

    manifest = IngestionManifest(storage, parsed_rel)
    state = {
        "source_sha256": source_document.sha256,
        "source_mtime": source_document.mtime,
        "parsed_sha256": content_hash("parsed body"),
        "parser_version": PARSER_VERSION,
        "indexed_parsed_sha256": content_hash("parsed body"),
        "indexed_chunker_version": CHUNKER_VERSION,
        "indexed_embedding_model": "test-model",
    }
    if sparse_state is not None:
        state["indexed_sparse_version"] = sparse_state
    manifest.documents["report.md"] = state
    manifest.save()
    mocker.patch.object(indexing, "get_storage", return_value=storage)
    mocker.patch.object(indexing, "EmbeddingService", return_value=_Embeddings())
    return storage, raw_rel, parsed_rel, manifest, source_document


@pytest.mark.asyncio
async def test_dense_only_collections_are_left_untouched(tmp_path, mocker):
    storage, raw_rel, parsed_rel, manifest, document = _indexed_dataset(
        tmp_path,
        mocker,
        sparse_state=None,
    )
    qdrant = mocker.Mock()
    qdrant.collection_exists.return_value = True
    qdrant.sparse_enabled.return_value = False
    qdrant.get_document_mtimes.return_value = {"report.md": document.mtime}
    mocker.patch.object(indexing, "QdrantAdapter", return_value=qdrant)
    replace = mocker.patch.object(indexing, "replace_document")

    result = await indexing.reconcile_index(
        "example",
        raw_rel,
        parsed_rel,
        sources=[document],
        manifest=manifest,
    )

    # Rebuilding a legacy collection would re-embed the whole dataset, so it
    # only happens on an explicit rebuild.
    assert result.indexed == 0
    replace.assert_not_called()


@pytest.mark.asyncio
async def test_missing_sparse_vectors_trigger_reindexing(tmp_path, mocker):
    storage, raw_rel, parsed_rel, manifest, document = _indexed_dataset(
        tmp_path,
        mocker,
        sparse_state=None,
    )
    qdrant = mocker.Mock()
    qdrant.collection_exists.return_value = True
    qdrant.sparse_enabled.return_value = True
    qdrant.get_document_mtimes.return_value = {"report.md": document.mtime}
    mocker.patch.object(indexing, "QdrantAdapter", return_value=qdrant)
    replace = mocker.patch.object(indexing, "replace_document")

    result = await indexing.reconcile_index(
        "example",
        raw_rel,
        parsed_rel,
        sources=[document],
        manifest=manifest,
    )

    assert result.indexed == 1
    assert replace.call_args.kwargs["with_sparse"] is True
    loaded = IngestionManifest.load(storage, parsed_rel)
    assert (
        loaded.documents["report.md"]["indexed_sparse_version"]
        == SPARSE_ENCODER_VERSION
    )


@pytest.mark.asyncio
async def test_current_sparse_index_is_not_rebuilt(tmp_path, mocker):
    _storage, raw_rel, parsed_rel, manifest, document = _indexed_dataset(
        tmp_path,
        mocker,
        sparse_state=SPARSE_ENCODER_VERSION,
    )
    qdrant = mocker.Mock()
    qdrant.collection_exists.return_value = True
    qdrant.sparse_enabled.return_value = True
    qdrant.get_document_mtimes.return_value = {"report.md": document.mtime}
    mocker.patch.object(indexing, "QdrantAdapter", return_value=qdrant)
    replace = mocker.patch.object(indexing, "replace_document")

    result = await indexing.reconcile_index(
        "example",
        raw_rel,
        parsed_rel,
        sources=[document],
        manifest=manifest,
    )

    assert result.indexed == 0
    replace.assert_not_called()
