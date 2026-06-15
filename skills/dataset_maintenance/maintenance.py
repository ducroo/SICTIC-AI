from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lib.adapters.qdrant import QdrantAdapter, QdrantAdmin
from lib.logger import get_logger
from lib.model_config import embedding_model
from lib.slugify import slugify
from lib.storage import get_storage
from lib.datasets.paths import dataset_parsed_path, list_all_dataset_names

logger = get_logger(__name__)


@dataclass(frozen=True)
class CollectionDiagnostic:
    collection: str
    dataset: str
    status: str


def orphaned_qdrant_collections(
    embeddings: Optional[str] = None,
    *,
    admin: QdrantAdmin | None = None,
) -> list[str]:
    model = embeddings or embedding_model()
    suffix = f"-{slugify(model.split('/')[-1])}"
    present_datasets = set(list_all_dataset_names())
    collections = (admin or QdrantAdmin()).list_collections()
    return sorted(
        collection
        for collection in collections
        if collection.endswith(suffix)
        and collection[:-len(suffix)] not in present_datasets
    )


def diagnose_qdrant_collections(
    embeddings: Optional[str] = None,
    *,
    admin: QdrantAdmin | None = None,
) -> list[CollectionDiagnostic]:
    model = embeddings or embedding_model()
    suffix = f"-{slugify(model.split('/')[-1])}"
    present_datasets = set(list_all_dataset_names())
    diagnostics = []
    for collection in sorted((admin or QdrantAdmin()).list_collections()):
        if not collection.endswith(suffix):
            continue
        dataset = collection[:-len(suffix)]
        diagnostics.append(
            CollectionDiagnostic(
                collection=collection,
                dataset=dataset,
                status="present" if dataset in present_datasets else "orphaned",
            )
        )
    return diagnostics


def prune_orphaned_qdrant_collections(
    embeddings: Optional[str] = None,
    *,
    apply: bool = False,
    admin: QdrantAdmin | None = None,
) -> list[str]:
    qdrant_admin = admin or QdrantAdmin()
    orphans = orphaned_qdrant_collections(
        embeddings,
        admin=qdrant_admin,
    )
    if apply:
        for collection in orphans:
            qdrant_admin.delete_collection(collection)
            logger.info("Deleted orphaned Qdrant collection: %s", collection)
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
        prefix = f"{dataset_slug}-"
        deleted = [
            collection
            for collection in all_collections
            if collection.startswith(prefix)
        ]
        for collection in deleted:
            admin.delete_collection(collection)
        storage = get_storage()
        parsed_path = dataset_parsed_path(dataset_slug)
        if storage.exists(parsed_path):
            storage.rmtree(parsed_path)
        return deleted

    if dataset and embeddings:
        collection = QdrantAdapter.collection_for(
            slugify(dataset),
            embeddings,
        )
        if collection in all_collections:
            admin.delete_collection(collection)
            deleted.append(collection)
        return deleted

    suffix = f"-{slugify(embeddings or '')}"
    deleted = [
        collection
        for collection in all_collections
        if collection.endswith(suffix)
    ]
    for collection in deleted:
        admin.delete_collection(collection)
    return deleted
