from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lib.infrastructure.qdrant import QdrantAdapter, QdrantAdmin
from lib.datasets.manifest import IngestionManifest
from lib.infrastructure.logging import get_logger
from lib.model_config import embedding_model
from lib.slugify import slugify
from lib.storage import get_storage
from lib.datasets.paths import dataset_parsed_path, list_all_dataset_names
from lib.datasets.state import activate_dataset, archive_dataset

logger = get_logger(__name__)

# Cleared when an index is rebuilt so reconciliation re-embeds every document.
_INDEX_STATE_KEYS = (
    "indexed_parsed_sha256",
    "indexed_chunker_version",
    "indexed_embedding_model",
    "indexed_sparse_version",
)


def _reset_manifest_index_state(
    dataset: str,
    *,
    embeddings: str | None = None,
) -> int:
    """Clear index checkpoints, optionally only for one embedding model."""
    dataset_slug = slugify(dataset)
    storage = get_storage()
    parsed_path = dataset_parsed_path(dataset_slug)
    if not storage.exists(parsed_path):
        return 0
    manifest = IngestionManifest.load(storage, parsed_path)
    expected_model_slug = (
        slugify(embeddings.split("/")[-1])
        if embeddings is not None
        else None
    )
    documents_reset = 0
    for state in manifest.documents.values():
        indexed_model = state.get("indexed_embedding_model")
        if expected_model_slug is not None and (
            not indexed_model
            or slugify(str(indexed_model).split("/")[-1])
            != expected_model_slug
        ):
            continue
        if not any(key in state for key in _INDEX_STATE_KEYS):
            continue
        for key in _INDEX_STATE_KEYS:
            state.pop(key, None)
        documents_reset += 1
    if documents_reset:
        manifest.indexed_dataset_revision = ""
        manifest.save()
    return documents_reset


@dataclass(frozen=True)
class CollectionDiagnostic:
    collection: str
    dataset: str
    status: str


@dataclass(frozen=True)
class IndexRebuild:
    dataset: str
    collection: str
    collection_deleted: bool
    documents_reset: int


def orphaned_qdrant_collections(
    embeddings: Optional[str] = None,
    *,
    adapter: QdrantAdapter | None = None,
) -> list[str]:
    """Return indexed dataset tenants that no longer exist in storage."""
    model = embeddings or embedding_model()
    present_datasets = set(list_all_dataset_names())
    indexed_datasets = (
        adapter or QdrantAdapter("dataset-maintenance", embeddings_model=model)
    ).list_indexed_datasets()
    return sorted(
        dataset
        for dataset in indexed_datasets
        if dataset not in present_datasets
    )


def diagnose_qdrant_collections(
    embeddings: Optional[str] = None,
    *,
    adapter: QdrantAdapter | None = None,
) -> list[CollectionDiagnostic]:
    model = embeddings or embedding_model()
    qdrant = adapter or QdrantAdapter(
        "dataset-maintenance",
        embeddings_model=model,
    )
    present_datasets = set(list_all_dataset_names())
    return [
        CollectionDiagnostic(
            collection=qdrant.collection_name,
            dataset=dataset,
            status="present" if dataset in present_datasets else "orphaned",
        )
        for dataset in qdrant.list_indexed_datasets()
    ]


def prune_orphaned_qdrant_collections(
    embeddings: Optional[str] = None,
    *,
    apply: bool = False,
    adapter: QdrantAdapter | None = None,
) -> list[str]:
    model = embeddings or embedding_model()
    qdrant = adapter or QdrantAdapter(
        "dataset-maintenance",
        embeddings_model=model,
    )
    orphans = orphaned_qdrant_collections(
        model,
        adapter=qdrant,
    )
    if apply:
        for dataset in orphans:
            qdrant.delete_dataset(dataset)
            logger.info("Deleted orphaned Qdrant dataset tenant: %s", dataset)
    return orphans


def delete_dataset_index(
    dataset: Optional[str] = None,
    embeddings: Optional[str] = None,
) -> list[str]:
    if not dataset and not embeddings:
        raise ValueError(
            "Must provide either a dataset or an embeddings target to delete."
        )

    admin = QdrantAdmin()
    all_collections = admin.list_collections()
    deleted = []

    if dataset and not embeddings:
        dataset_slug = slugify(dataset)
        shared_collections = [
            collection
            for collection in all_collections
            if collection.startswith("sictic-ai-datasets-")
        ]
        for collection in shared_collections:
            model_slug = collection.removeprefix("sictic-ai-datasets-")
            adapter = QdrantAdapter(
                dataset_slug,
                embeddings_model=model_slug,
            )
            if adapter.delete_dataset():
                deleted.append(collection)
        storage = get_storage()
        parsed_path = dataset_parsed_path(dataset_slug)
        if storage.exists(parsed_path):
            storage.rmtree(parsed_path)
        return deleted

    if dataset and embeddings:
        dataset_slug = slugify(dataset)
        adapter = QdrantAdapter(
            dataset_slug,
            embeddings_model=embeddings,
        )
        if adapter.delete_dataset():
            deleted.append(adapter.collection_name)
        _reset_manifest_index_state(
            dataset_slug,
            embeddings=embeddings,
        )
        return deleted

    collection = QdrantAdapter.collection_for("", embeddings)
    if collection in all_collections:
        admin.delete_collection(collection)
        deleted.append(collection)
        for dataset_name in list_all_dataset_names():
            _reset_manifest_index_state(
                dataset_name,
                embeddings=embeddings,
            )
    return deleted


def rebuild_dataset_index(
    dataset: str,
) -> IndexRebuild:
    """Rebuild one dataset tenant with the configured embedding model."""
    if not dataset:
        raise ValueError("Must provide --dataset/-d.")

    dataset_slug = slugify(dataset)
    adapter = QdrantAdapter(dataset_slug)
    collection = adapter.collection_name
    collection_deleted = adapter.delete_dataset()
    if collection_deleted:
        logger.info(
            "Deleted dataset %s from shared Qdrant collection %s for rebuild.",
            dataset_slug,
            collection,
        )

    documents_reset = _reset_manifest_index_state(dataset_slug)

    return IndexRebuild(
        dataset=dataset_slug,
        collection=collection,
        collection_deleted=collection_deleted,
        documents_reset=documents_reset,
    )


def activate_dataset_marker(dataset: str) -> str:
    if not dataset:
        raise ValueError("Must provide --dataset/-d.")
    activate_dataset(dataset)
    return slugify(dataset)


def archive_dataset_marker(dataset: str) -> str:
    if not dataset:
        raise ValueError("Must provide --dataset/-d.")
    archive_dataset(dataset)
    return slugify(dataset)
