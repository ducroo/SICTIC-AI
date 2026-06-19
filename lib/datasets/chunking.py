from __future__ import annotations

import hashlib
import uuid

from langchain_text_splitters import MarkdownTextSplitter

from lib.datasets.models import Chunk


def split_markdown(text: str, filename: str, mod_time: float) -> list[Chunk]:
    splitter = MarkdownTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = splitter.create_documents([text])
    chunks = []
    for index, doc in enumerate(docs):
        content = doc.page_content
        chunk_hash = hashlib.md5(
            f"{filename}_{content}".encode("utf-8")
        ).hexdigest()
        chunks.append(
            Chunk(
                chunk_id=str(uuid.UUID(hex=chunk_hash)),
                document_name=filename,
                page_number=(index // 5) + 1,
                last_modified=mod_time,
                text=content,
            )
        )
    return chunks
