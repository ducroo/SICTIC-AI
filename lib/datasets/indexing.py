"""Reconcile parsed Markdown documents into Qdrant."""

from __future__ import annotations

from lib.adapters.qdrant import QdrantAdapter
from lib.datasets.chunking import split_markdown
from lib.datasets.embeddings import EmbeddingService
from lib.datasets.manifest import (
    CHUNKER_VERSION,
    PARSER_VERSION,
    IngestionManifest,
    content_hash,
    ignored_parse_is_current,
)
from lib.datasets.models import IngestionFailure, IngestionResult
from lib.datasets.source import (
    SourceDocument,
    parsed_filepath,
    snapshot_source_files,
)
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

MAX_CHUNKS_PER_DOCUMENT = 500
MAX_CHARACTERS_PER_DOCUMENT = 500_000


async def reconcile_index(
    dataset_name: str,
    raw_rel: str,
    parsed_rel: str,
    *,
    sources: list[SourceDocument] | None = None,
    manifest: IngestionManifest | None = None,
    result: IngestionResult | None = None,
) -> IngestionResult:
    """Reconcile successfully parsed documents to Qdrant."""
    dataset_slug = slugify(dataset_name)
    storage = get_storage()
    sources = sources or snapshot_source_files(storage, raw_rel)
    manifest = manifest or IngestionManifest.load(storage, parsed_rel)
    result = result or IngestionResult(dataset=dataset_slug)
    embeddings = EmbeddingService()
    qdrant = QdrantAdapter(dataset_slug)
    collection_exists = qdrant.collection_exists()
    db_mtimes = (
        qdrant.get_document_mtimes(raise_on_error=True)
        if collection_exists
        else {}
    )

    indexable_source_names = {
        source.filename
        for source in sources
        if not ignored_parse_is_current(
            manifest.documents.get(source.filename),
            source_sha256=source.sha256,
        )
    }
    for orphan in sorted(set(db_mtimes) - indexable_source_names):
        qdrant.delete_document(orphan, raise_on_error=True)
        result.removed_qdrant += 1
        logger.info("[%s] Removed Qdrant orphan %s.", dataset_slug, orphan)

    files_to_index: list[tuple[SourceDocument, str, str]] = []
    for source in sources:
        state = manifest.documents.get(source.filename, {})
        parsed_path = parsed_filepath(parsed_rel, source.filename)
        if (
            state.get("source_sha256") != source.sha256
            or state.get("parser_version") != PARSER_VERSION
            or not storage.exists(parsed_path)
        ):
            continue

        parsed_text = storage.read_text(parsed_path)
        parsed_sha = content_hash(parsed_text)
        if state.get("parsed_sha256") != parsed_sha:
            result.failures.append(
                IngestionFailure(
                    filename=source.filename,
                    stage="index",
                    error=(
                        "Parsed content changed outside ingestion; "
                        "reconversion required."
                    ),
                )
            )
            continue

        if (
            not state.get("indexed_parsed_sha256")
            and db_mtimes.get(source.filename, 0) >= source.mtime
        ):
            state.update(
                {
                    "indexed_parsed_sha256": parsed_sha,
                    "indexed_chunker_version": CHUNKER_VERSION,
                    "indexed_embedding_model": embeddings.model,
                }
            )

        if (
            state.get("indexed_parsed_sha256") != parsed_sha
            or state.get("indexed_chunker_version") != CHUNKER_VERSION
            or state.get("indexed_embedding_model") != embeddings.model
        ):
            files_to_index.append((source, parsed_path, parsed_text))

    manifest.save()
    if not files_to_index:
        manifest.update_indexed_dataset_revision()
        manifest.save()
        logger.info("[%s] No documents require indexing.", dataset_slug)
        return result

    non_empty_files = [item for item in files_to_index if item[2].strip()]
    if non_empty_files:
        qdrant.ensure_collection(embeddings.vector_size())
        collection_exists = True

    logger.info(
        "[%s] Indexing %s documents.",
        dataset_slug,
        len(files_to_index),
    )
    for index, (source, _parsed_path, text) in enumerate(
        files_to_index,
        start=1,
    ):
        try:
            if len(text) > MAX_CHARACTERS_PER_DOCUMENT:
                _skip_oversized_document(
                    qdrant=qdrant,
                    collection_exists=collection_exists,
                    source=source,
                    state=manifest.state(source.filename),
                    embeddings=embeddings,
                    parsed_text=text,
                    reason=(
                        f"{len(text):,} characters exceeds the "
                        f"{MAX_CHARACTERS_PER_DOCUMENT:,}-character limit"
                    ),
                )
                result.ignored += 1
                logger.warning(
                    "[%s] Skipped indexing %s/%s for %s: document has "
                    "%s characters (limit %s).",
                    dataset_slug,
                    index,
                    len(files_to_index),
                    source.filename,
                    f"{len(text):,}",
                    f"{MAX_CHARACTERS_PER_DOCUMENT:,}",
                )
                manifest.save()
                continue
            chunks = (
                split_markdown(text, source.filename, source.mtime)
                if text.strip()
                else []
            )
            if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
                _skip_oversized_document(
                    qdrant=qdrant,
                    collection_exists=collection_exists,
                    source=source,
                    state=manifest.state(source.filename),
                    embeddings=embeddings,
                    parsed_text=text,
                    reason=(
                        f"{len(chunks):,} chunks exceeds the "
                        f"{MAX_CHUNKS_PER_DOCUMENT:,}-chunk limit"
                    ),
                )
                result.ignored += 1
                logger.warning(
                    "[%s] Skipped indexing %s/%s for %s: document has "
                    "%s chunks (limit %s).",
                    dataset_slug,
                    index,
                    len(files_to_index),
                    source.filename,
                    f"{len(chunks):,}",
                    f"{MAX_CHUNKS_PER_DOCUMENT:,}",
                )
                manifest.save()
                continue
            if collection_exists:
                await replace_document(
                    qdrant,
                    embeddings,
                    source.filename,
                    chunks,
                )
            state = manifest.state(source.filename)
            state.update(
                {
                    "indexed_parsed_sha256": content_hash(text),
                    "indexed_chunker_version": CHUNKER_VERSION,
                    "indexed_embedding_model": embeddings.model,
                }
            )
            state.pop("index_ignored_reason", None)
            result.indexed += 1
            logger.info(
                "[%s] Indexed %s/%s: %s (%s chunks)",
                dataset_slug,
                index,
                len(files_to_index),
                source.filename,
                len(chunks),
            )
        except Exception as error:
            result.failures.append(
                IngestionFailure(
                    filename=source.filename,
                    stage="index",
                    error=str(error),
                )
            )
            logger.error(
                "[%s] Indexing failed %s/%s for %s: %s",
                dataset_slug,
                index,
                len(files_to_index),
                source.filename,
                error,
            )
        manifest.save()

    manifest.update_indexed_dataset_revision()
    manifest.save()
    return result


def _skip_oversized_document(
    *,
    qdrant: QdrantAdapter,
    collection_exists: bool,
    source: SourceDocument,
    state: dict,
    embeddings: EmbeddingService,
    parsed_text: str,
    reason: str,
) -> None:
    """Checkpoint a deliberately omitted document without stale vectors."""
    if collection_exists:
        qdrant.delete_document(source.filename, raise_on_error=True)
    state.update(
        {
            "indexed_parsed_sha256": content_hash(parsed_text),
            "indexed_chunker_version": CHUNKER_VERSION,
            "indexed_embedding_model": embeddings.model,
            "index_ignored_reason": reason,
        }
    )


async def replace_document(
    qdrant: QdrantAdapter,
    embeddings: EmbeddingService,
    filename: str,
    chunks,
) -> None:
    """Upsert a complete replacement before removing obsolete chunk IDs."""
    existing_ids = qdrant.get_document_point_ids(filename)
    vectors = await embeddings.embed_many([chunk.text for chunk in chunks])
    points = []
    for chunk, vector in zip(chunks, vectors):
        payload = chunk.model_dump()
        payload.pop("chunk_id", None)
        payload.pop("score", None)
        points.append(
            {
                "id": chunk.chunk_id,
                "vector": vector,
                "payload": payload,
            }
        )
    qdrant.upsert_points(points)
    qdrant.delete_point_ids(
        existing_ids - {point["id"] for point in points}
    )
