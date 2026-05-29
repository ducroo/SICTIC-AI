import sys
import os
import uuid
import hashlib
from typing import List, Optional

# Suppress annoying grpc/absl console warnings
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_TRACE"] = ""

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from skills.dataset_chat.core.models import Chunk
from langchain_text_splitters import MarkdownTextSplitter
from lib.slugify import slugify
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

class Chunker:
    @staticmethod
    def split_markdown(text: str, filename: str, mod_time: float) -> List[Chunk]:
        splitter = MarkdownTextSplitter(chunk_size=1000, chunk_overlap=100)
        docs = splitter.create_documents([text])
        chunks = []
        for i, doc in enumerate(docs):
            content = doc.page_content
            hash_str = f"{filename}_{content}"
            chunk_hash = hashlib.md5(hash_str.encode('utf-8')).hexdigest()
            chunk_id = str(uuid.UUID(hex=chunk_hash))
            
            chunks.append(Chunk(
                chunk_id=chunk_id,
                document_name=filename,
                page_number=(i // 5) + 1,
                last_modified=mod_time,
                text=content
            ))
        return chunks

class QdrantAdapter:
    """Manages the connection and semantic operations with Qdrant."""
    @staticmethod
    def collection_for(collection_name: str, embeddings_model: Optional[str] = None) -> str:
        model = embeddings_model or get_env_var("DEFAULT_EMBEDDINGS")
        clean_model = model.split("/")[-1]
        return slugify(f"{collection_name}-{clean_model}")

    def __init__(self, collection_name: str):
        # Suppress litellm boot warnings
        import litellm
        litellm.suppress_debug_info = True

        self.client = QdrantClient(url="http://localhost:6333")
        model = get_env_var("DEFAULT_EMBEDDINGS")
        self.collection_name = self.collection_for(collection_name, model)

        collections = self.client.get_collections().collections
        collection_exists = any(c.name == self.collection_name for c in collections)
        vector_size = self._detect_vector_size(model)

        if collection_exists:
            existing_size = self._collection_vector_size()
            if existing_size is not None and existing_size != vector_size:
                points_count = self._collection_points_count()
                if points_count == 0:
                    logger.warning(
                        f"Recreating empty Qdrant collection {self.collection_name}: "
                        f"stored vector size {existing_size}, current model size {vector_size}."
                    )
                    self.client.delete_collection(self.collection_name)
                    collection_exists = False
                else:
                    raise RuntimeError(
                        f"Qdrant collection {self.collection_name} has vector size {existing_size}, "
                        f"but {model} returns {vector_size}. Delete/rebuild the collection before rerunning."
                    )

        if not collection_exists:
            logger.info(f"Creating new Qdrant collection: {self.collection_name}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    def _detect_vector_size(self, model: str) -> int:
        """Returns the embedding dimension for the configured model."""
        import litellm

        dummy_kwargs = {"model": model, "input": ["test"]}
        if model.startswith("ollama/"):
            dummy_kwargs["api_base"] = get_env_var("OLLAMA_HOST")

        try:
            dummy_response = litellm.embedding(**dummy_kwargs)
            vector_size = len(dummy_response.data[0]["embedding"])
            logger.info(f"Dynamically determined vector size: {vector_size} for model {model}")
            return vector_size
        except Exception as e:
            logger.error(f"Failed to determine vector size dynamically: {e}")
            raise RuntimeError(f"Could not determine embedding vector size for {model}: {e}")

    def _collection_info(self):
        try:
            return self.client.get_collection(self.collection_name)
        except Exception as e:
            logger.warning(f"Failed to inspect Qdrant collection {self.collection_name}: {e}")
            return None

    def _collection_vector_size(self) -> int | None:
        info = self._collection_info()
        if not info:
            return None
        vectors = getattr(getattr(info, "config", None), "params", None)
        vectors = getattr(vectors, "vectors", None)
        return getattr(vectors, "size", None)

    def _collection_points_count(self) -> int:
        info = self._collection_info()
        return int(getattr(info, "points_count", 0) or 0) if info else 0

    def dataset_available(self) -> bool:
        """Returns True when the collection exists and contains at least one point."""
        try:
            count = self.client.count(
                collection_name=self.collection_name,
                exact=False,
            )
            return count.count > 0
        except Exception as e:
            logger.warning(f"Failed to check Qdrant dataset availability for {self.collection_name}: {e}")
            return False

    async def _get_embedding(self, text: str) -> List[float]:
        import litellm
        model = get_env_var("DEFAULT_EMBEDDINGS")
        kwargs = {"model": model, "input": [text]}
        if model.startswith("ollama/"):
            kwargs["api_base"] = get_env_var("OLLAMA_HOST")
            
        try:
            response = await litellm.aembedding(**kwargs)
            return response.data[0]["embedding"]
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise RuntimeError(f"Embedding failed: {e}")

    def get_document_mtimes(self) -> dict[str, float]:
        """Returns a dict of document_name -> newest last_modified timestamp in Qdrant."""
        try:
            scroll_result = self.client.scroll(
                collection_name=self.collection_name,
                limit=10000,
                with_payload=["document_name", "last_modified"],
                with_vectors=False
            )[0]
            
            mtimes = {}
            for point in scroll_result:
                doc_name = point.payload["document_name"]
                mtime = point.payload["last_modified"]
                if doc_name not in mtimes or mtime > mtimes[doc_name]:
                    mtimes[doc_name] = mtime
            return mtimes
        except Exception as e:
            logger.warning(f"Failed to fetch document mtimes: {e}")
            return {}

    def delete_document(self, document_name: str) -> None:
        """Deletes all chunks belonging to a specific document."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_name",
                            match=MatchValue(value=document_name)
                        )
                    ]
                )
            )
            logger.debug(f"Deleted old chunks for {document_name} from Qdrant.")
        except Exception as e:
            logger.error(f"Failed to delete {document_name} from Qdrant: {e}")

    async def upsert(self, chunks: List[Chunk]) -> None:
        if not chunks:
            return
            
        points = []
        for c in chunks:
            vector = await self._get_embedding(c.text)
            points.append(PointStruct(
                id=c.chunk_id,
                vector=vector,
                payload=c.model_dump()
            ))
            
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
        except Exception as e:
            logger.error(f"Failed to upsert points: {e}")
            raise RuntimeError(f"Upsert failed: {e}")

    async def search(self, query: str | list[str], limit: int = 5, threshold_factor: float = 0.8) -> List[Chunk]:
        if not query:
            logger.warning("Empty query provided to search.")
            return []
            
        if isinstance(query, list):
            query = " ".join(query)
            
        vector = await self._get_embedding(query)
        
        try:
            # Qdrant client 1.18.0 deprecates .search() in favor of .query_points()
            results = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                limit=limit,
                with_payload=True
            ).points
            
            if not results:
                return []
                
            top_score = results[0].score
            threshold = top_score * threshold_factor
            
            filtered_results = [r for r in results if r.score >= threshold]
            
            return [Chunk(**r.payload) for r in filtered_results]
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
