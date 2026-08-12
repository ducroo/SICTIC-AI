from __future__ import annotations

import hashlib
import uuid

from langchain_text_splitters import MarkdownTextSplitter

from lib.datasets.models import Chunk
from lib.datasets.page_markers import split_text_by_pages
from lib.datasets.text_normalization import normalize_extracted_text


def split_markdown(text: str, filename: str, mod_time: float) -> list[Chunk]:
    text = normalize_extracted_text(text)
    splitter = MarkdownTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks: list[Chunk] = []
    for page_number, section_text in split_text_by_pages(text):
        if not section_text.strip():
            continue
        for doc in splitter.create_documents([section_text]):
            content = doc.page_content
            chunk_hash = hashlib.md5(
                f"{filename}_{content}".encode("utf-8")
            ).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=str(uuid.UUID(hex=chunk_hash)),
                    document_name=filename,
                    page_number=page_number,
                    last_modified=mod_time,
                    text=content,
                )
            )
    return chunks
