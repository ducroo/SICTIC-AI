"""Firestore vector-store adapter mirroring QdrantAdapter's surface."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from lib.logger import get_logger
from lib.model_config import embedding_model
from lib.slugify import slugify

logger = get_logger(__name__)

_META_COLLECTION = "_sictic_vector_meta"
_CHUNKS_SUBCOLLECTION = "chunks"
_DISTANCE_RESULT_FIELD = "vector_distance"


@dataclass
class FirestoreQueryHit:
    id: str
    payload: dict[str, Any]
    score: float


def _firestore_client():
    try:
        from google.cloud import firestore
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError(
            "google-cloud-firestore is required for VECTOR_STORE=firestore. "
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
        return firestore.Client(project=project_id, credentials=credentials)

    # Application Default Credentials / Cloud Agent workload identity.
    if project_id:
        return firestore.Client(project=project_id)
    # Fall back to ADC default project resolution.
    return firestore.Client()


class FirestoreAdmin:
    """Database administration operations not tied to one dataset."""

    def __init__(self):
        self.client = _firestore_client()

    def list_collections(self) -> list[str]:
        names: list[str] = []
        for meta in self.client.collection(_META_COLLECTION).stream():
            names.append(meta.id)
        return sorted(names)

    def delete_collection(self, collection_name: str) -> None:
        FirestoreAdapter(collection_name)._delete_all_chunks()
        self.client.collection(_META_COLLECTION).document(collection_name).delete()


class FirestoreAdapter:
    """Vector store backed by Firestore documents + find_nearest."""

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
        self.client = _firestore_client()
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
        return FirestoreAdmin().list_collections()

    def collection_exists(self) -> bool:
        return self._meta.get().exists

    def ensure_collection(self, vector_size: int) -> None:
        snap = self._meta.get()
        if snap.exists:
            existing = int((snap.to_dict() or {}).get("vector_size") or 0)
            if existing and existing != vector_size:
                if self.collection_points_count() == 0:
                    logger.warning(
                        "Recreating empty Firestore collection %s: stored "
                        "vector size %s, current model size %s.",
                        self.collection_name,
                        existing,
                        vector_size,
                    )
                    self.delete_collection()
                else:
                    raise RuntimeError(
                        f"Firestore collection {self.collection_name} has "
                        f"vector size {existing}, but the configured "
                        f"embedding model returns {vector_size}. "
                        "Delete/rebuild the collection before rerunning."
                    )
            else:
                self._meta.set(
                    {
                        "vector_size": vector_size,
                        "backend": "firestore",
                    },
                    merge=True,
                )
                return
        logger.info(
            "Registering Firestore vector collection: %s (dim=%s). "
            "Create a vector index on field 'embedding' if find_nearest fails.",
            self.collection_name,
            vector_size,
        )
        self._meta.set(
            {
                "vector_size": vector_size,
                "backend": "firestore",
            }
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
                "Deleted chunks for %s from Firestore.",
                document_name,
            )
        except Exception as exc:
            logger.error(
                "Failed to delete %s from Firestore: %s",
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
        from google.cloud.firestore_v1.vector import Vector

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
                "Firestore collection %s does not exist; returning zero chunks.",
                self.collection_name,
            )
            return []

        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

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
                f"Firestore vector query failed for {self.collection_name}: "
                f"{exc}. Ensure a cosine vector index exists on "
                f"'{self.collection_name}/index/{_CHUNKS_SUBCOLLECTION}' "
                "field 'embedding'."
            ) from exc

        hits: list[FirestoreQueryHit] = []
        for doc in docs:
            data = dict(doc.to_dict() or {})
            distance = float(data.pop(_DISTANCE_RESULT_FIELD, 0.0) or 0.0)
            data.pop("embedding", None)
            # Cosine distance in Firestore is 1 - cosine_similarity.
            score = 1.0 - distance
            hits.append(
                FirestoreQueryHit(
                    id=doc.id,
                    payload=data,
                    score=score,
                )
            )
        if not hits:
            logger.warning(
                "Firestore collection %s exists but the query returned zero chunks.",
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
