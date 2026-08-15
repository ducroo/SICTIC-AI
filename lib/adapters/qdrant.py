from __future__ import annotations

from typing import Optional

from lib.datasets.sparse import SparseVectorData
from lib.env import get_env_var
from lib.logger import get_logger
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
    """Database-only operations for one Qdrant collection."""

    @staticmethod
    def collection_for(
        collection_name: str,
        embeddings_model: Optional[str] = None,
    ) -> str:
        model = embeddings_model or embedding_model()
        clean_model = model.split("/")[-1]
        return slugify(f"{collection_name}-{clean_model}")

    def __init__(
        self,
        collection_name: str,
        *,
        vector_size: int | None = None,
    ):
        self.client = QdrantClient(url=get_env_var("QDRANT_HOST"))
        self.collection_name = self.collection_for(collection_name)
        self._sparse_enabled: bool | None = None
        if vector_size is not None:
            self.ensure_collection(vector_size)

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
                points_count = self.collection_points_count()
                if points_count == 0:
                    logger.warning(
                        "Recreating empty Qdrant collection %s: stored vector "
                        "size %s, current model size %s.",
                        self.collection_name,
                        existing_size,
                        vector_size,
                    )
                    self.delete_collection()
                else:
                    raise RuntimeError(
                        f"Qdrant collection {self.collection_name} has vector "
                        f"size {existing_size}, but the configured embedding "
                        f"model returns {vector_size}. Delete/rebuild the "
                        "collection before rerunning."
                    )
            else:
                return
        logger.info("Creating new Qdrant collection: %s", self.collection_name)
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE,
            ),
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)
            },
        )
        self._sparse_enabled = None

    def sparse_enabled(self) -> bool:
        """Whether this collection stores BM25 sparse vectors for hybrid search.

        Collections created before hybrid search have no sparse vector
        configuration, and Qdrant cannot add one to an existing collection.
        Those collections stay dense-only until they are rebuilt.
        """
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
        info = self.collection_info()
        return int(getattr(info, "points_count", 0) or 0) if info else 0

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
        document_filter = Filter(
            must=[
                FieldCondition(
                    key="document_name",
                    match=MatchValue(value=document_name),
                )
            ]
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
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_name",
                            match=MatchValue(value=document_name),
                        )
                    ]
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
    ) -> None:
        qdrant_points = [
            PointStruct(
                id=point["id"],
                vector=self._point_vector(point),
                payload=point["payload"],
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
                    limit=branch_limit,
                ),
                Prefetch(
                    query=SparseVector(
                        indices=list(sparse.indices),
                        values=list(sparse.values),
                    ),
                    using=SPARSE_VECTOR_NAME,
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

    def delete_collection(self) -> None:
        self.client.delete_collection(self.collection_name)
        self._sparse_enabled = None
