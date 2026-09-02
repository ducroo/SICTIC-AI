"""Assemble dedicated documents and incidental mentions for a person."""

import re
from pathlib import PurePath
from typing import List, Tuple

from lib.datasets.models import Chunk
from lib.datasets.paths import dataset_parsed_path
from lib.datasets.search import dataset_search
from lib.datasets.source import parsed_filepath
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

MAX_FULL_DOCUMENT_CHARACTERS = 20_000
_PERSONAL_DOCUMENT_PATTERNS = (
    re.compile(r"\bcvs?\b"),
    re.compile(r"\bcurriculum vitae\b"),
    re.compile(r"\bresumes?\b"),
    re.compile(r"\bpassports?\b"),
    re.compile(r"\b(?:id|identity) cards?\b"),
    re.compile(r"\bcriminal records?\b"),
    re.compile(r"\bemployment records?\b"),
    re.compile(r"\breference letters?\b"),
    re.compile(r"\brecommendation letters?\b"),
)


def _filename_tokens(filename: str) -> list[str]:
    basename = PurePath(filename.replace("\\", "/")).name
    return slugify(basename).split("-")


def person_in_filename(filename: str, person_name: str) -> bool:
    """Return whether the filename identifies the person without substrings."""
    filename_tokens = _filename_tokens(filename)
    name_tokens = slugify(person_name).split("-")
    if not filename_tokens or not name_tokens:
        return False

    name_length = len(name_tokens)
    if any(
        filename_tokens[index:index + name_length] == name_tokens
        for index in range(len(filename_tokens) - name_length + 1)
    ):
        return True

    if len(name_tokens) < 2:
        return False
    first_name, surname = name_tokens[0], name_tokens[-1]
    if surname not in filename_tokens:
        return False
    return first_name in filename_tokens or first_name[0] in filename_tokens


def is_personal_document(filename: str) -> bool:
    """Return whether the filename describes a personal-record document."""
    normalized = " ".join(_filename_tokens(filename))
    return any(pattern.search(normalized) for pattern in _PERSONAL_DOCUMENT_PATTERNS)


async def get_filtered_chunks(dataset_name: str, name: str, query: str) -> list:
    """
    Retrieve chunks for a person from a dataset and apply a content filter 
    to ensure the person is actually mentioned.
    """
    logger.info(f"Collating profile chunks for '{name}' in dataset '{dataset_name}'...")
    
    chunks = await dataset_search(
        dataset_name=dataset_name,
        query=query,
        max_chunks=500
    )
    
    if not chunks:
        return []

    # Filter chunks based on name words
    filter_words = [w.lower() for w in name.split() if w.strip()]
    
    content_filtered = []
    for chunk in chunks:
        if all(fw in chunk.text.lower() for fw in filter_words):
            content_filtered.append(chunk)

    return content_filtered

async def build_person_dossier(dataset_name: str, person_name: str, query: str) -> Tuple[List[Chunk], List[Chunk]]:
    """
    Retrieves and logically splits Qdrant chunks into a dedicated 'dossier' (full docs)
    and 'mentions' (isolated chunks), excluding any LinkedIn data.
    """
    logger.info(f"[{dataset_name}] Building dossier for '{person_name}'...")
    dataset_slug = slugify(dataset_name)
    parsed_root = dataset_parsed_path(dataset_slug)
    
    dossier: List[Chunk] = []
    mentions: List[Chunk] = []
    
    filtered_chunks = await get_filtered_chunks(dataset_name, person_name, query)
    
    if not filtered_chunks:
        return dossier, mentions
        
    # Reverse to get chronological/least-to-most relevant order based on how Qdrant returns them
    filtered_chunks.reverse()
    
    storage = get_storage()
    seen_dossier_docs = set()
    
    for c in filtered_chunks:
        doc_name = c.document_name
        
        # Actively exclude LinkedIn data
        if "linkedin" in doc_name.lower():
            continue
            
        # If we already pulled this full document into the dossier, skip processing its chunks
        if doc_name in seen_dossier_docs:
            continue
            
        should_expand = (
            person_in_filename(doc_name, person_name)
            or is_personal_document(doc_name)
        )
        # Qdrant stores the original document name. Resolve its parsed path
        # through the same convention used by conversion and indexing.
        full_md_path = parsed_filepath(parsed_root, doc_name)
        
        if should_expand and storage.exists(full_md_path):
            full_text = storage.read_text(full_md_path)
            if len(full_text) <= MAX_FULL_DOCUMENT_CHARACTERS:
                full_chunk = Chunk(
                    chunk_id=f"{doc_name}-all",
                    document_name=doc_name,
                    page_number="all",
                    last_modified=c.last_modified,
                    text=full_text,
                    score=c.score
                )
                dossier.append(full_chunk)
                seen_dossier_docs.add(doc_name)
            else:
                mentions.append(c)
        else:
            mentions.append(c)
            
    logger.info(f"[{dataset_name}] Dossier built: {len(dossier)} full docs, {len(mentions)} mentions.")
    return dossier, mentions
