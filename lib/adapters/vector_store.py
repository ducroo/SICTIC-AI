"""Select the vector store backend used during indexing and search."""

from __future__ import annotations

import os
from typing import Optional, Protocol

from lib.logger import get_logger

logger = get_logger(__name__)

DEFAULT_VECTOR_STORE = "qdrant"
SUPPORTED_VECTOR_STORES = frozenset({"qdrant", "firestore"})


class VectorStore(Protocol):
    """Shared surface used by indexing, search, and ephemeral datasets."""

    collection_name: str

    @staticmethod
    def collection_for(
        collection_name: str,
        embeddings_model: Optional[str] = None,
    ) -> str: ...

    def collection_exists(self) -> bool: ...

    def ensure_collection(self, vector_size: int) -> None: ...

    def get_document_mtimes(
        self,
        *,
        raise_on_error: bool = False,
    ) -> dict[str, float]: ...

    def get_document_point_ids(self, document_name: str) -> set[str]: ...

    def delete_point_ids(self, point_ids: set[str]) -> None: ...

    def delete_document(
        self,
        document_name: str,
        *,
        raise_on_error: bool = False,
    ) -> None: ...

    def upsert_points(
        self,
        points: list[dict],
        *,
        batch_size: int = 50,
    ) -> None: ...

    def query(self, vector: list[float], *, limit: int): ...

    def delete_collection(self) -> None: ...


class VectorStoreAdmin(Protocol):
    def list_collections(self) -> list[str]: ...

    def delete_collection(self, collection_name: str) -> None: ...


def vector_store_backend() -> str:
    raw = (os.environ.get("VECTOR_STORE") or DEFAULT_VECTOR_STORE).strip()
    backend = raw.lower()
    if backend not in SUPPORTED_VECTOR_STORES:
        raise ValueError(
            f"Unsupported VECTOR_STORE={raw!r}; "
            f"expected one of {sorted(SUPPORTED_VECTOR_STORES)}"
        )
    return backend


def get_vector_store(
    collection_name: str,
    *,
    vector_size: int | None = None,
) -> VectorStore:
    backend = vector_store_backend()
    if backend == "firestore":
        from lib.adapters.firestore import FirestoreAdapter

        logger.info("Using Firestore vector store for %s.", collection_name)
        return FirestoreAdapter(
            collection_name,
            vector_size=vector_size,
        )

    from lib.adapters.qdrant import QdrantAdapter

    logger.info("Using Qdrant vector store for %s.", collection_name)
    return QdrantAdapter(collection_name, vector_size=vector_size)


def get_vector_store_admin() -> VectorStoreAdmin:
    backend = vector_store_backend()
    if backend == "firestore":
        from lib.adapters.firestore import FirestoreAdmin

        return FirestoreAdmin()

    from lib.adapters.qdrant import QdrantAdmin

    return QdrantAdmin()


def collection_for(
    collection_name: str,
    embeddings_model: Optional[str] = None,
) -> str:
    """Collection naming shared by Qdrant and Firestore backends."""
    backend = vector_store_backend()
    if backend == "firestore":
        from lib.adapters.firestore import FirestoreAdapter

        return FirestoreAdapter.collection_for(
            collection_name,
            embeddings_model,
        )

    from lib.adapters.qdrant import QdrantAdapter

    return QdrantAdapter.collection_for(collection_name, embeddings_model)
