from __future__ import annotations

import threading
from datetime import date
from typing import Optional
from uuid import NAMESPACE_URL, uuid5

from lib.datasets.sparse import SparseVectorData
from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.logging import get_logger
from lib.model_config import embedding_model
from lib.runtime_noise import configure_runtime_noise, suppress_native_stderr
from lib.slugify import slugify

configure_runtime_noise()

with suppress_native_stderr():
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        Fusion,
        FusionQuery,
        KeywordIndexParams,
        KeywordIndexType,
        MatchValue,
        Modifier,
        PointIdsList,
        PointStruct,
        Prefetch,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )

logger = get_logger(__name__)

# Dense vectors stay on Qdrant's default unnamed vector so that collections
# created before hybrid search remain queryable without migration.
DENSE_VECTOR_NAME = ""
SPARSE_VECTOR_NAME = "bm25"
DATASET_PAYLOAD_KEY = "dataset_slug"
SHARED_COLLECTION_PREFIX = "sictic-ai-datasets"
LEGACY_MIGRATION_REMOVE_AFTER = date(2026, 10, 23)

_INDEX_STATE_KEYS = (
    "indexed_parsed_sha256",
    "indexed_chunker_version",
    "indexed_embedding_model",
    "indexed_sparse_version",
)
_layout_lock = threading.Lock()
_checked_layouts: set[str] = set()


class QdrantAdmin:
    """Database administration operations not tied to one dataset."""

    def __init__(self):
        self.client = QdrantClient(
            url=get_env_var("QDRANT_HOST"),
            timeout=60.0,
        )

    def list_collections(self) -> list[str]:
        return [
            collection.name
            for collection in self.client.get_collections().collections
        ]

    def delete_collection(self, collection_name: str) -> None:
        self.client.delete_collection(collection_name)


class QdrantAdapter:
    """Dataset-scoped operations within one collection per embedding model."""

    @staticmethod
    def collection_for(
        _collection_name: str,
        embeddings_model: Optional[str] = None,
    ) -> str:
        model = embeddings_model or embedding_model()
        clean_model = model.split("/")[-1]
        return slugify(f"{SHARED_COLLECTION_PREFIX}-{clean_model}")

    @staticmethod
    def legacy_collection_for(
        dataset_name: str,
        embeddings_model: Optional[str] = None,
    ) -> str:
        model = embeddings_model or embedding_model()
        clean_model = model.split("/")[-1]
        return slugify(f"{dataset_name}-{clean_model}")

    def __init__(
        self,
        collection_name: str,
        *,
        vector_size: int | None = None,
        embeddings_model: str | None = None,
    ):
        self.client = QdrantClient(url=get_env_var("QDRANT_HOST"))
        self.dataset_slug = slugify(collection_name)
        self.embeddings_model = embeddings_model or embedding_model()
        self.collection_name = self.collection_for(
            self.dataset_slug,
            self.embeddings_model,
        )
        self._sparse_enabled: bool | None = None
        self._ensure_shared_layout()
        if vector_size is not None:
            self.ensure_collection(vector_size)

    def _ensure_shared_layout(self) -> None:
        """Delete exact legacy dataset collections after preparing the shared one."""
        layout_key = slugify(self.embeddings_model)
        if layout_key in _checked_layouts:
            return
        with _layout_lock:
            if layout_key in _checked_layouts:
                return
            from lib.datasets.paths import list_all_dataset_names

            legacy_by_name = {
                self.legacy_collection_for(dataset, self.embeddings_model): dataset
                for dataset in list_all_dataset_names()
            }
            existing = set(self.list_collections())
            legacy_names = sorted(
                existing.intersection(legacy_by_name) - {self.collection_name}
            )
            if legacy_names:
                legacy_info = self.client.get_collection(legacy_names[0])
                params = getattr(
                    getattr(legacy_info, "config", None),
                    "params",
                    None,
                )
                vectors = getattr(params, "vectors", None)
                vector_size = getattr(vectors, "size", None)
                if not vector_size:
                    raise RuntimeError(
                        "Could not determine the vector size required to "
                        f"migrate legacy collection {legacy_names[0]!r}."
                    )
                if self.collection_name not in existing:
                    self._create_collection(int(vector_size))
                else:
                    self.ensure_collection(int(vector_size))

                for legacy_name in legacy_names:
                    dataset = legacy_by_name[legacy_name]
                    self._reset_dataset_index_state(dataset)
                    self.client.delete_collection(legacy_name)
                    logger.warning(
                        "Deleted legacy SICTIC-AI Qdrant collection %s; "
                        "dataset %s will rebuild in %s.",
                        legacy_name,
                        dataset,
                        self.collection_name,
                    )
                logger.warning(
                    "Temporary Qdrant legacy migration is scheduled for "
                    "removal after %s.",
                    LEGACY_MIGRATION_REMOVE_AFTER.isoformat(),
                )
            elif self.collection_name in existing:
                if not self.sparse_enabled():
                    raise RuntimeError(
                        f"Shared Qdrant collection {self.collection_name} has "
                        f"no {SPARSE_VECTOR_NAME!r} sparse vector configuration."
                    )
                self._ensure_tenant_index()
            _checked_layouts.add(layout_key)

    @staticmethod
    def _reset_dataset_index_state(dataset_name: str) -> None:
        from lib.datasets.manifest import IngestionManifest
        from lib.datasets.paths import dataset_parsed_path
        from lib.storage import get_storage

        storage = get_storage()
        parsed_path = dataset_parsed_path(dataset_name)
        if not storage.exists(parsed_path):
            return
        manifest = IngestionManifest.load(storage, parsed_path)
        changed = False
        for state in manifest.documents.values():
            for key in _INDEX_STATE_KEYS:
                if key in state:
                    state.pop(key, None)
                    changed = True
        if changed or manifest.indexed_dataset_revision:
            manifest.indexed_dataset_revision = ""
            manifest.save()

    def _create_collection(self, vector_size: int) -> None:
        logger.info("Creating shared Qdrant collection: %s", self.collection_name)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)
            },
            on_disk_payload=True,
        )
        self._ensure_tenant_index()
        self._sparse_enabled = None

    def _ensure_tenant_index(self) -> None:
        info = self.client.get_collection(self.collection_name)
        payload_schema = getattr(info, "payload_schema", None) or {}
        if DATASET_PAYLOAD_KEY in payload_schema:
            return
        self.client.create_payload_index(
            collection_name=self.collection_name,
            field_name=DATASET_PAYLOAD_KEY,
            field_schema=KeywordIndexParams(
                type=KeywordIndexType.KEYWORD,
                is_tenant=True,
            ),
            wait=True,
        )

    def _dataset_filter_for(
        self,
        dataset_slug: str,
        *conditions: FieldCondition,
    ) -> Filter:
        return Filter(
            must=[
                FieldCondition(
                    key=DATASET_PAYLOAD_KEY,
                    match=MatchValue(value=slugify(dataset_slug)),
                ),
                *conditions,
            ]
        )

    def _dataset_filter(self, *conditions: FieldCondition) -> Filter:
        return self._dataset_filter_for(self.dataset_slug, *conditions)

    def _stored_point_id(self, point_id: str | int) -> str:
        return str(
            uuid5(
                NAMESPACE_URL,
                f"sictic-ai:{self.dataset_slug}:{point_id}",
            )
        )

    def list_collections(self) -> list[str]:
        return [
            collection.name
            for collection in self.client.get_collections().collections
        ]

    def collection_exists(self) -> bool:
        return self.collection_name in self.list_collections()

    def ensure_collection(self, vector_size: int) -> None:
        if self.collection_exists():
            existing_size = self.collection_vector_size()
            if existing_size is not None and existing_size != vector_size:
                points_count = int(
                    getattr(
                        self.client.count(self.collection_name, exact=True),
                        "count",
                        0,
                    )
                    or 0
                )
                if points_count == 0:
                    logger.warning(
                        "Recreating empty Qdrant collection %s: stored vector "
                        "size %s, current model size %s.",
                        self.collection_name,
                        existing_size,
                        vector_size,
                    )
                    self.client.delete_collection(self.collection_name)
                else:
                    raise RuntimeError(
                        f"Qdrant collection {self.collection_name} has vector "
                        f"size {existing_size}, but the configured embedding "
                        f"model returns {vector_size}. Delete/rebuild the "
                        "collection before rerunning."
                    )
            else:
                if not self.sparse_enabled():
                    raise RuntimeError(
                        f"Shared Qdrant collection {self.collection_name} has "
                        f"no {SPARSE_VECTOR_NAME!r} sparse vector configuration."
                    )
                self._ensure_tenant_index()
                return
        self._create_collection(vector_size)

    def sparse_enabled(self) -> bool:
        """Whether the shared collection stores BM25 sparse vectors."""
        if self._sparse_enabled is None:
            info = self.collection_info()
            params = getattr(getattr(info, "config", None), "params", None)
            sparse_vectors = getattr(params, "sparse_vectors", None) or {}
            self._sparse_enabled = SPARSE_VECTOR_NAME in sparse_vectors
        return self._sparse_enabled

    def collection_info(self):
        try:
            return self.client.get_collection(self.collection_name)
        except Exception as exc:
            logger.warning(
                "Failed to inspect Qdrant collection %s: %s",
                self.collection_name,
                exc,
            )
            return None

    def collection_vector_size(self) -> int | None:
        info = self.collection_info()
        if not info:
            return None
        vectors = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(vectors, "vectors", None)
        return getattr(vectors, "size", None)

    def collection_points_count(self) -> int:
        if not self.collection_exists():
            return 0
        result = self.client.count(
            collection_name=self.collection_name,
            count_filter=self._dataset_filter(),
            exact=True,
        )
        return int(getattr(result, "count", 0) or 0)

    def list_indexed_datasets(self) -> list[str]:
        """Return tenant dataset slugs stored in the shared collection."""
        if not self.collection_exists():
            return []
        response = self.client.facet(
            collection_name=self.collection_name,
            key=DATASET_PAYLOAD_KEY,
            limit=10000,
            exact=True,
        )
        return sorted(
            str(hit.value)
            for hit in getattr(response, "hits", [])
        )

    def get_document_mtimes(
        self,
        *,
        raise_on_error: bool = False,
    ) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        offset = None
        try:
            while True:
                points, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=self._dataset_filter(),
                    limit=10000,
                    offset=offset,
                    with_payload=["document_name", "last_modified"],
                    with_vectors=False,
                )
                for point in points:
                    doc_name = point.payload["document_name"]
                    mtime = point.payload["last_modified"]
                    if doc_name not in mtimes or mtime > mtimes[doc_name]:
                        mtimes[doc_name] = mtime
                if offset is None:
                    break
            return mtimes
        except Exception as exc:
            logger.warning("Failed to fetch document mtimes: %s", exc)
            if raise_on_error:
                raise RuntimeError(
                    f"Failed to fetch document mtimes from {self.collection_name}: {exc}"
                ) from exc
            return {}

    def get_document_point_ids(self, document_name: str) -> set[str]:
        point_ids: set[str] = set()
        offset = None
        document_filter = self._dataset_filter(
            FieldCondition(
                key="document_name",
                match=MatchValue(value=document_name),
            )
        )
        try:
            while True:
                points, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=document_filter,
                    limit=10000,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False,
                )
                point_ids.update(str(point.id) for point in points)
                if offset is None:
                    break
            return point_ids
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch existing chunks for {document_name}: {exc}"
            ) from exc

    def delete_point_ids(self, point_ids: set[str]) -> None:
        if not point_ids:
            return
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=PointIdsList(points=sorted(point_ids)),
                wait=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to delete {len(point_ids)} stale chunks: {exc}"
            ) from exc

    def delete_document(
        self,
        document_name: str,
        *,
        raise_on_error: bool = False,
    ) -> None:
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=self._dataset_filter(
                    FieldCondition(
                        key="document_name",
                        match=MatchValue(value=document_name),
                    )
                ),
                wait=True,
            )
            logger.debug("Deleted chunks for %s from Qdrant.", document_name)
        except Exception as exc:
            logger.error(
                "Failed to delete %s from Qdrant: %s",
                document_name,
                exc,
            )
            if raise_on_error:
                raise RuntimeError(
                    f"Failed to delete existing chunks for {document_name}: {exc}"
                ) from exc

    @staticmethod
    def _point_vector(point: dict):
        """Return the dense vector, or a named map when sparse data is present."""
        sparse: SparseVectorData | None = point.get("sparse")
        if sparse is None:
            return point["vector"]
        return {
            DENSE_VECTOR_NAME: point["vector"],
            SPARSE_VECTOR_NAME: SparseVector(
                indices=list(sparse.indices),
                values=list(sparse.values),
            ),
        }

    def upsert_points(
        self,
        points: list[dict],
        *,
        batch_size: int = 50,
    ) -> set[str]:
        stored_ids = {
            self._stored_point_id(point["id"])
            for point in points
        }
        qdrant_points = [
            PointStruct(
                id=self._stored_point_id(point["id"]),
                vector=self._point_vector(point),
                payload={
                    **point["payload"],
                    DATASET_PAYLOAD_KEY: self.dataset_slug,
                },
            )
            for point in points
        ]
        total = len(qdrant_points)
        for start in range(0, total, batch_size):
            batch = qdrant_points[start:start + batch_size]
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch,
                )
                logger.info(
                    "Upserted point batch %s-%s of %s into %s.",
                    start + 1,
                    start + len(batch),
                    total,
                    self.collection_name,
                )
            except Exception as exc:
                logger.error("Failed to upsert points: %s", exc)
                raise RuntimeError(f"Upsert failed: {exc}") from exc
        return stored_ids

    def query(self, vector: list[float], *, limit: int):
        if not self.collection_exists():
            logger.warning(
                "Qdrant collection %s does not exist; returning zero chunks.",
                self.collection_name,
            )
            return []

        points = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            query_filter=self._dataset_filter(),
            limit=limit,
            with_payload=True,
        ).points
        if not points:
            logger.warning(
                "Qdrant collection %s exists but the query returned zero chunks.",
                self.collection_name,
            )
        return points

    def query_hybrid(
        self,
        vector: list[float],
        sparse: SparseVectorData,
        *,
        limit: int,
        candidate_limit: int | None = None,
    ):
        """Fuse dense and BM25 rankings with reciprocal rank fusion in Qdrant."""
        if not sparse or not self.sparse_enabled():
            return self.query(vector, limit=limit)
        if not self.collection_exists():
            logger.warning(
                "Qdrant collection %s does not exist; returning zero chunks.",
                self.collection_name,
            )
            return []

        branch_limit = candidate_limit or limit
        points = self.client.query_points(
            collection_name=self.collection_name,
            prefetch=[
                Prefetch(
                    query=vector,
                    using=DENSE_VECTOR_NAME,
                    filter=self._dataset_filter(),
                    limit=branch_limit,
                ),
                Prefetch(
                    query=SparseVector(
                        indices=list(sparse.indices),
                        values=list(sparse.values),
                    ),
                    using=SPARSE_VECTOR_NAME,
                    filter=self._dataset_filter(),
                    limit=branch_limit,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            with_payload=True,
        ).points
        if not points:
            logger.warning(
                "Qdrant collection %s exists but the query returned zero chunks.",
                self.collection_name,
            )
        return points

    def delete_dataset(self, dataset_slug: str | None = None) -> bool:
        """Delete this dataset's points without affecting other tenants."""
        selected_dataset = slugify(dataset_slug or self.dataset_slug)
        if not self.collection_exists():
            return False
        dataset_filter = self._dataset_filter_for(selected_dataset)
        count = self.client.count(
            collection_name=self.collection_name,
            count_filter=dataset_filter,
            exact=True,
        )
        if int(getattr(count, "count", 0) or 0) == 0:
            return False
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=dataset_filter,
            wait=True,
        )
        return True
