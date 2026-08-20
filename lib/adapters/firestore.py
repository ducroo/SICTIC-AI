"""Firestore vector-store adapter mirroring QdrantAdapter's surface."""  # pragma: allowlist secret

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from lib.adapters.vector_store import FIRESTORE_MAX_VECTOR_DIM  # pragma: allowlist secret
from lib.logger import get_logger
from lib.model_config import embedding_model
from lib.slugify import slugify

logger = get_logger(__name__)

_META_COLLECTION = "_sictic_vector_meta"
_CHUNKS_SUBCOLLECTION = "chunks"
_DISTANCE_RESULT_FIELD = "vector_distance"
_DEFAULT_DATABASE = "(default)"


def _index_covers_embedding(index, vector_size: int) -> bool:
    fields = getattr(index, "fields", None) or []
    for field in fields:
        path = getattr(field, "field_path", None)
        config = getattr(field, "vector_config", None)
        if path != "embedding" or config is None:
            continue
        dimension = getattr(config, "dimension", None)
        if int(dimension or 0) == int(vector_size):
            return True
    return False


@dataclass
class FirestoreQueryHit:  # pragma: allowlist secret
    id: str
    payload: dict[str, Any]
    score: float


def _firestore_client():  # pragma: allowlist secret
    try:
        from google.cloud import firestore  # pragma: allowlist secret
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError(
            "google-cloud-firestore is required for VECTOR_STORE=firestore. "  # pragma: allowlist secret
            "Install it into sictic-env (see environment.yml)."
        ) from error

    project_id = (
        os.environ.get("FIREBASE_PROJECT_ID")
        or os.environ.get("GCLOUD_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()
    sa_json = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    if sa_json:
        info = json.loads(sa_json)
        credentials = service_account.Credentials.from_service_account_info(info)
        project_id = project_id or info.get("project_id", "")
        if not project_id:
            raise RuntimeError(
                "FIREBASE_PROJECT_ID is required when using a service account."
            )
        return firestore.Client(project=project_id, credentials=credentials)  # pragma: allowlist secret

    # Application Default Credentials / Cloud Agent workload identity.
    if project_id:
        return firestore.Client(project=project_id)  # pragma: allowlist secret
    # Fall back to ADC default project resolution.
    return firestore.Client()  # pragma: allowlist secret


class FirestoreAdmin:  # pragma: allowlist secret
    """Database administration operations not tied to one dataset."""

    def __init__(self):
        self.client = _firestore_client()  # pragma: allowlist secret

    def list_collections(self) -> list[str]:
        names: list[str] = []
        for meta in self.client.collection(_META_COLLECTION).stream():
            names.append(meta.id)
        return sorted(names)

    def delete_collection(self, collection_name: str) -> None:
        FirestoreAdapter(collection_name)._delete_all_chunks()  # pragma: allowlist secret
        self.client.collection(_META_COLLECTION).document(collection_name).delete()


class FirestoreAdapter:  # pragma: allowlist secret
    """Vector store backed by Firestore documents + find_nearest."""  # pragma: allowlist secret

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
        self.client = _firestore_client()  # pragma: allowlist secret
        self.collection_name = self.collection_for(collection_name)
        self._chunks = self.client.collection(
            self.collection_name
        ).document("index").collection(_CHUNKS_SUBCOLLECTION)
        self._meta = self.client.collection(_META_COLLECTION).document(
            self.collection_name
        )
        if vector_size is not None:
            self.ensure_collection(vector_size)

    def list_collections(self) -> list[str]:
        return FirestoreAdmin().list_collections()  # pragma: allowlist secret

    def collection_exists(self) -> bool:
        return self._meta.get().exists

    def ensure_collection(self, vector_size: int) -> None:
        if vector_size > FIRESTORE_MAX_VECTOR_DIM:  # pragma: allowlist secret
            raise RuntimeError(
                f"Firestore vector search max dimension is "  # pragma: allowlist secret
                f"{FIRESTORE_MAX_VECTOR_DIM}, got {vector_size}. "  # pragma: allowlist secret
                "Set FIRESTORE_EMBEDDING_DIMENSIONS to 1536 (or at most 2048) "  # pragma: allowlist secret
                "or use a smaller embedding model."
            )
        snap = self._meta.get()
        if snap.exists:
            existing = int((snap.to_dict() or {}).get("vector_size") or 0)
            if existing and existing != vector_size:
                if self.collection_points_count() == 0:
                    logger.warning(
                        "Recreating empty Firestore collection %s: stored "  # pragma: allowlist secret
                        "vector size %s, current model size %s.",
                        self.collection_name,
                        existing,
                        vector_size,
                    )
                    self.delete_collection()
                else:
                    raise RuntimeError(
                        f"Firestore collection {self.collection_name} has "  # pragma: allowlist secret
                        f"vector size {existing}, but the configured "
                        f"embedding model returns {vector_size}. "
                        "Delete/rebuild the collection before rerunning."
                    )
            else:
                self._meta.set(
                    {
                        "vector_size": vector_size,
                        "backend": "firestore",  # pragma: allowlist secret
                    },
                    merge=True,
                )
                self._ensure_vector_index(vector_size)
                return
        logger.info(
            "Registering Firestore vector collection: %s (dim=%s).",  # pragma: allowlist secret
            self.collection_name,
            vector_size,
        )
        self._meta.set(
            {
                "vector_size": vector_size,
                "backend": "firestore",  # pragma: allowlist secret
            }
        )
        self._ensure_vector_index(vector_size)


    def _ensure_vector_index(self, vector_size: int) -> None:
        """Create a cosine/flat vector index on chunks.embedding if missing."""
        try:
            from google.api_core.exceptions import AlreadyExists
            from google.cloud.firestore_admin_v1 import FirestoreAdminClient  # pragma: allowlist secret
            from google.cloud.firestore_admin_v1.types import Index  # pragma: allowlist secret
        except ImportError as error:
            logger.warning(
                "Skipping Firestore vector index ensure; admin client missing: %s",  # pragma: allowlist secret
                error,
            )
            return

        project = getattr(self.client, "project", None) or (
            os.environ.get("FIREBASE_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or ""
        )
        if not project:
            logger.warning("Skipping Firestore vector index ensure; no project id.")  # pragma: allowlist secret
            return
        credentials = getattr(self.client, "_credentials", None)
        admin = FirestoreAdminClient(credentials=credentials)  # pragma: allowlist secret
        parent = (
            f"projects/{project}/databases/{_DEFAULT_DATABASE}"
            f"/collectionGroups/{_CHUNKS_SUBCOLLECTION}"
        )
        try:
            for existing in admin.list_indexes(parent=parent):
                if _index_covers_embedding(existing, vector_size):
                    logger.info(
                        "Firestore vector index already present for dim=%s.",  # pragma: allowlist secret
                        vector_size,
                    )
                    return
            index = Index(
                query_scope=Index.QueryScope.COLLECTION,
                fields=[
                    Index.IndexField(
                        field_path="embedding",
                        vector_config=Index.IndexField.VectorConfig(
                            dimension=vector_size,
                            flat=Index.IndexField.VectorConfig.FlatIndex(),
                        ),
                    )
                ],
            )
            admin.create_index(parent=parent, index=index)
            logger.info(
                "Creating Firestore vector index on %s.embedding (dim=%s).",  # pragma: allowlist secret
                _CHUNKS_SUBCOLLECTION,
                vector_size,
            )
        except AlreadyExists:
            logger.info(
                "Firestore vector index already exists for dim=%s.",  # pragma: allowlist secret
                vector_size,
            )
        except Exception as exc:
            logger.warning(
                "Could not ensure Firestore vector index (dim=%s): %s. "  # pragma: allowlist secret
                "find_nearest will fail until a cosine index exists on "
                "'*/index/%s'.embedding.",
                vector_size,
                exc,
                _CHUNKS_SUBCOLLECTION,
            )

    def collection_vector_size(self) -> int | None:
        snap = self._meta.get()
        if not snap.exists:
            return None
        size = (snap.to_dict() or {}).get("vector_size")
        return int(size) if size is not None else None

    def collection_points_count(self) -> int:
        return sum(1 for _ in self._chunks.select([]).stream())

    def get_document_mtimes(
        self,
        *,
        raise_on_error: bool = False,
    ) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        try:
            for doc in self._chunks.select(
                ["document_name", "last_modified"]
            ).stream():
                data = doc.to_dict() or {}
                doc_name = data.get("document_name")
                mtime = data.get("last_modified")
                if not doc_name or mtime is None:
                    continue
                mtime_f = float(mtime)
                if doc_name not in mtimes or mtime_f > mtimes[doc_name]:
                    mtimes[doc_name] = mtime_f
            return mtimes
        except Exception as exc:
            logger.warning("Failed to fetch document mtimes: %s", exc)
            if raise_on_error:
                raise RuntimeError(
                    f"Failed to fetch document mtimes from "
                    f"{self.collection_name}: {exc}"
                ) from exc
            return {}

    def get_document_point_ids(self, document_name: str) -> set[str]:
        try:
            docs = (
                self._chunks.where("document_name", "==", document_name)
                .select([])
                .stream()
            )
            return {doc.id for doc in docs}
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch existing chunks for {document_name}: {exc}"
            ) from exc

    def delete_point_ids(self, point_ids: set[str]) -> None:
        if not point_ids:
            return
        try:
            batch = self.client.batch()
            pending = 0
            for point_id in point_ids:
                batch.delete(self._chunks.document(point_id))
                pending += 1
                if pending >= 400:
                    batch.commit()
                    batch = self.client.batch()
                    pending = 0
            if pending:
                batch.commit()
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
            self.delete_point_ids(self.get_document_point_ids(document_name))
            logger.debug(
                "Deleted chunks for %s from Firestore.",  # pragma: allowlist secret
                document_name,
            )
        except Exception as exc:
            logger.error(
                "Failed to delete %s from Firestore: %s",  # pragma: allowlist secret
                document_name,
                exc,
            )
            if raise_on_error:
                raise RuntimeError(
                    f"Failed to delete existing chunks for {document_name}: {exc}"
                ) from exc

    def upsert_points(
        self,
        points: list[dict],
        *,
        batch_size: int = 50,
    ) -> None:
        from google.cloud.firestore_v1.vector import Vector  # pragma: allowlist secret

        total = len(points)
        for start in range(0, total, batch_size):
            batch_points = points[start : start + batch_size]
            batch = self.client.batch()
            for point in batch_points:
                payload = dict(point.get("payload") or {})
                data = {
                    **payload,
                    "embedding": Vector(list(point["vector"])),
                }
                batch.set(self._chunks.document(str(point["id"])), data)
            try:
                batch.commit()
                logger.info(
                    "Upserted point batch %s-%s of %s into %s.",
                    start + 1,
                    start + len(batch_points),
                    total,
                    self.collection_name,
                )
            except Exception as exc:
                logger.error("Failed to upsert points: %s", exc)
                raise RuntimeError(f"Upsert failed: {exc}") from exc

    def query(self, vector: list[float], *, limit: int):
        if not self.collection_exists():
            logger.warning(
                "Firestore collection %s does not exist; returning zero chunks.",  # pragma: allowlist secret
                self.collection_name,
            )
            return []

        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure  # pragma: allowlist secret
        from google.cloud.firestore_v1.vector import Vector  # pragma: allowlist secret

        try:
            docs = (
                self._chunks.find_nearest(
                    vector_field="embedding",
                    query_vector=Vector(vector),
                    distance_measure=DistanceMeasure.COSINE,
                    limit=limit,
                    distance_result_field=_DISTANCE_RESULT_FIELD,
                ).get()
            )
        except Exception as exc:
            raise RuntimeError(
                f"Firestore vector query failed for {self.collection_name}: "  # pragma: allowlist secret
                f"{exc}. Ensure a cosine vector index exists on "
                f"'{self.collection_name}/index/{_CHUNKS_SUBCOLLECTION}' "
                "field 'embedding'."
            ) from exc

        hits: list[FirestoreQueryHit] = []  # pragma: allowlist secret
        for doc in docs:
            data = dict(doc.to_dict() or {})
            distance = float(data.pop(_DISTANCE_RESULT_FIELD, 0.0) or 0.0)
            data.pop("embedding", None)
            # Cosine distance in Firestore is 1 - cosine_similarity.  # pragma: allowlist secret
            score = 1.0 - distance
            hits.append(
                FirestoreQueryHit(  # pragma: allowlist secret
                    id=doc.id,
                    payload=data,
                    score=score,
                )
            )
        if not hits:
            logger.warning(
                "Firestore collection %s exists but the query returned zero chunks.",  # pragma: allowlist secret
                self.collection_name,
            )
        return hits

    def delete_collection(self) -> None:
        self._delete_all_chunks()
        self._meta.delete()

    def _delete_all_chunks(self) -> None:
        while True:
            docs = list(self._chunks.limit(400).stream())
            if not docs:
                break
            batch = self.client.batch()
            for doc in docs:
                batch.delete(doc.reference)
            batch.commit()
