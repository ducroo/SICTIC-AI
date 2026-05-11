import sys
import os
import uuid
from typing import List, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from skills.dataset_chat.core.models import Chunk

import hashlib
import uuid
from langchain_text_splitters import MarkdownTextSplitter

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

from skills.utils.env import get_env_var
from skills.utils.logger import get_logger

logger = get_logger(__name__)

class QdrantAdapter:
    def __init__(self, collection_name: str):
        from skills.utils.slugify import slugify
        self.client = QdrantClient(url=get_env_var("QDRANT_HOST"), timeout=60.0)
        self.default_embeddings = get_env_var("DEFAULT_EMBEDDINGS")
        clean_model = self.default_embeddings.split("/")[-1]
        self.collection_name = slugify(f"{collection_name}-{clean_model}")
        self.ollama_url = get_env_var("OLLAMA_HOST").rstrip("/")
        self._cached_dimension = None
        self.ensure_collection()

    async def get_embedding(self, text: str, priority=None) -> List[float]:
        from skills.utils.services_gateway import gateway, Priority
        if priority is None:
            priority = Priority.STANDARD
            
        if not text.strip():
            return [0.0] * self.get_dimension()
            
        try:
            kwargs = {
                "model": self.default_embeddings,
                "input": [text]
            }
            if self.default_embeddings.startswith("ollama/"):
                kwargs["api_base"] = self.ollama_url
                
            response = await gateway.request_embedding(kwargs, priority=priority)
            return response.data[0]["embedding"]
        except Exception as e:
            logger.error(f"Critical failure: Could not get embedding: {e}")
            return [0.0] * self.get_dimension()

    def get_dimension(self) -> int:
        if self._cached_dimension is not None:
            return self._cached_dimension
            
        import litellm
        import time
        retries = 3
        for attempt in range(retries):
            try:
                kwargs = {
                    "model": self.default_embeddings,
                    "input": ["the lazy fox jumped over the low fence"]
                }
                if self.default_embeddings.startswith("ollama/"):
                    kwargs["api_base"] = self.ollama_url
                    
                response = litellm.embedding(**kwargs)
                self._cached_dimension = len(response.data[0]["embedding"])
                return self._cached_dimension
            except Exception as e:
                logger.warning(f"Failed to get dimension (attempt {attempt+1}/{retries}): {e}")
                time.sleep(2)
                
        logger.error("Critial failure: Could not get embedding dimension from model.")
        raise RuntimeError(f"Could not determine dimension for model {self.default_embeddings}.")

    def ensure_collection(self):
        if not self.client.collection_exists(self.collection_name):
            dim = self.get_dimension()
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
            )
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id="00000000-0000-0000-0000-000000000000",
                        vector=[0.0] * dim,
                        payload={
                            "is_metadata": True,
                            "PROVIDER_EMBEDDINGS": self.default_embeddings,
                            "DATASET_NAME": self.collection_name
                        }
                    )
                ]
            )
        else:
            res = self.client.retrieve(self.collection_name, ids=["00000000-0000-0000-0000-000000000000"])
            if res and res[0].payload:
                stored_emb = res[0].payload.get("PROVIDER_EMBEDDINGS")
                if stored_emb and stored_emb != self.default_embeddings:
                    raise ValueError(f"Embedding model mismatch! Stored: {stored_emb}, Current: {self.default_embeddings}. Aborting to prevent vector contamination.")

    def dataset_available(self) -> bool:
        """Checks if the dataset collection exists and contains at least one vector."""
        from qdrant_client.http.exceptions import UnexpectedResponse
        try:
            collection_info = self.client.get_collection(collection_name=self.collection_name)
            # The metadata point counts as 1, so we need more than 1 point to consider it populated with actual data
            # Actually, let's just check if points_count > 1 since we always inject a metadata point
            return collection_info.points_count > 1
        except UnexpectedResponse as e:
            if e.status_code == 404:
                return False
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to check dataset availability: {e}")

    def point_exists(self, filename: str) -> Optional[float]:
        res = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="document_name", match=MatchValue(value=filename))]
            ),
            limit=1,
            with_payload=True
        )
        if res and res[0]:
            return res[0][0].payload.get("last_modified")
        return None

    def get_all_document_mtimes(self) -> dict:
        """Fetch the last_modified time for all documents in the collection efficiently."""
        mtimes = {}
        offset = None
        while True:
            records, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                limit=10000,
                with_payload=["document_name", "last_modified"],
                with_vectors=False,
                offset=offset
            )
            for rec in records:
                if rec.payload:
                    doc_name = rec.payload.get("document_name")
                    mtime = rec.payload.get("last_modified")
                    if doc_name and mtime is not None:
                        if doc_name not in mtimes or mtime > mtimes[doc_name]:
                            mtimes[doc_name] = mtime
            if next_offset is None:
                break
            offset = next_offset
        return mtimes

    def delete_document_points(self, filename: str):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="document_name", match=MatchValue(value=filename))]
            )
        )

    def delete_collection(self):
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)
            logger.info(f"Collection {self.collection_name} deleted.")
        else:
            logger.info(f"Collection {self.collection_name} does not exist.")

    def upsert_chunks(self, chunks: List[Chunk]):
        batch_size = 50
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            points = []
            for chunk in batch:
                vector = self.get_embedding(chunk.text)
                points.append(
                    PointStruct(
                        id=chunk.chunk_id,
                        vector=vector,
                        payload={
                            "document_name": chunk.document_name,
                            "page_number": chunk.page_number,
                            "last_modified": chunk.last_modified,
                            "text": chunk.text
                        }
                    )
                )
            if points:
                self.client.upsert(collection_name=self.collection_name, points=points)

    async def ingest_documents_batch(self, parsed_documents: dict, mtimes: dict):
        import asyncio
        chunks = []
        for filename, text in parsed_documents.items():
            if not text:
                continue
            mod_time = mtimes.get(filename, 0.0)
            chunks.extend(Chunker.split_markdown(text, filename, mod_time))
            
        await self.upsert_chunks_async(chunks)

    async def upsert_chunks_async(self, chunks: List[Chunk]):
        import asyncio
        from skills.utils.services_gateway import Priority
        batch_size = 50
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            
            tasks = [self.get_embedding(chunk.text, priority=Priority.BULK) for chunk in batch]
            vectors = await asyncio.gather(*tasks)
            
            points = []
            for chunk, vector in zip(batch, vectors):
                points.append(
                    PointStruct(
                        id=chunk.chunk_id,
                        vector=vector,
                        payload={
                            "document_name": chunk.document_name,
                            "page_number": chunk.page_number,
                            "last_modified": chunk.last_modified,
                            "text": chunk.text
                        }
                    )
                )
            if points:
                # The Qdrant insert itself is lightning fast, so synchronous is fine here
                self.client.upsert(collection_name=self.collection_name, points=points)

    async def search(self, query: str, limit: int = 25, threshold_factor: Optional[float] = 0.8) -> List[Chunk]:
        query_vector = await self.get_embedding(query)
        res_obj = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True
        )
        res = res_obj.points
        
        if not res:
            return []

        if threshold_factor is not None:
            max_score = res[0].score
            threshold = max_score * threshold_factor
            
            valid_chunks = [p for p in res if p.score >= threshold]
            
            if len(valid_chunks) < 5:
                valid_chunks = res[:5]
        else:
            valid_chunks = res
        
        valid_chunks = [p for p in valid_chunks if not p.payload.get("is_metadata")]
        valid_chunks.sort(key=lambda x: x.score, reverse=True)
        
        return [
            Chunk(
                chunk_id=str(p.id),
                document_name=p.payload.get("document_name", "Unknown"),
                page_number=p.payload.get("page_number", 1),
                last_modified=p.payload.get("last_modified", 0.0),
                text=p.payload.get("text", ""),
                score=p.score
            )
            for p in valid_chunks
        ]
