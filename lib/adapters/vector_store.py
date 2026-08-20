"""Select the vector store backend used during indexing and search."""

from __future__ import annotations

import os
from typing import Optional, Protocol

from lib.logger import get_logger

logger = get_logger(__name__)

DEFAULT_VECTOR_STORE = "qdrant"
SUPPORTED_VECTOR_STORES = frozenset({"qdrant", "firestore"})  # pragma: allowlist secret
FIRESTORE_MAX_VECTOR_DIM = 2048  # pragma: allowlist secret
DEFAULT_FIRESTORE_VECTOR_DIM = 1536  # pragma: allowlist secret


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


def firestore_embedding_dimensions() -> int:  # pragma: allowlist secret
    """Dimension used for Firestore KNN (max 2048 on Standard edition)."""  # pragma: allowlist secret
    raw = (os.environ.get("FIRESTORE_EMBEDDING_DIMENSIONS") or "").strip()  # pragma: allowlist secret
    if not raw:
        return DEFAULT_FIRESTORE_VECTOR_DIM  # pragma: allowlist secret
    try:
        dim = int(raw)
    except ValueError as error:
        raise ValueError(
            f"FIRESTORE_EMBEDDING_DIMENSIONS must be an integer, got {raw!r}"  # pragma: allowlist secret
        ) from error
    if dim < 1 or dim > FIRESTORE_MAX_VECTOR_DIM:  # pragma: allowlist secret
        raise ValueError(
            f"FIRESTORE_EMBEDDING_DIMENSIONS={dim} is outside 1..{FIRESTORE_MAX_VECTOR_DIM}"  # pragma: allowlist secret
        )
    return dim


def get_vector_store(
    collection_name: str,
    *,
    vector_size: int | None = None,
) -> VectorStore:
    backend = vector_store_backend()
    if backend == "firestore":  # pragma: allowlist secret
        from lib.adapters.firestore import FirestoreAdapter  # pragma: allowlist secret

        logger.info("Using Firestore vector store for %s.", collection_name)  # pragma: allowlist secret
        return FirestoreAdapter(  # pragma: allowlist secret
            collection_name,
            vector_size=vector_size,
        )

    from lib.adapters.qdrant import QdrantAdapter

    logger.info("Using Qdrant vector store for %s.", collection_name)
    return QdrantAdapter(collection_name, vector_size=vector_size)


def get_vector_store_admin() -> VectorStoreAdmin:
    backend = vector_store_backend()
    if backend == "firestore":  # pragma: allowlist secret
        from lib.adapters.firestore import FirestoreAdmin  # pragma: allowlist secret

        return FirestoreAdmin()  # pragma: allowlist secret

    from lib.adapters.qdrant import QdrantAdmin

    return QdrantAdmin()


def collection_for(
    collection_name: str,
    embeddings_model: Optional[str] = None,
) -> str:
    """Collection naming shared by Qdrant and Firestore backends."""  # pragma: allowlist secret
    backend = vector_store_backend()
    if backend == "firestore":  # pragma: allowlist secret
        from lib.adapters.firestore import FirestoreAdapter  # pragma: allowlist secret

        return FirestoreAdapter.collection_for(  # pragma: allowlist secret
            collection_name,
            embeddings_model,
        )

    from lib.adapters.qdrant import QdrantAdapter

    return QdrantAdapter.collection_for(collection_name, embeddings_model)
