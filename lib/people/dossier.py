"""Assemble dedicated documents and incidental mentions for a person."""

import asyncio
import re
import unicodedata
from functools import lru_cache
from itertools import combinations
from pathlib import PurePath
from typing import List, Tuple

from lib.datasets.models import Chunk
from lib.datasets.paths import dataset_parsed_path
from lib.datasets.ingestion import sync_datasets
from lib.datasets.source import iter_parsed_chunks, parsed_filepath
from lib.infrastructure.configuration import load_repository_config
from lib.people.discovery import persons_in_dataset
from lib.people.model import Person, extract_email_addresses
from lib.people.linkedin.identity import extract_linkedin_ids
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


def _name_tokens(text: str) -> tuple[str, ...]:
    # Keep digits within words so e.g. Anna2 cannot match Anna. Underscores and
    # punctuation separate words, including in filenames. Preserve diacritics.
    return tuple(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


@lru_cache(maxsize=32)
def _unique_name_phrases(names: tuple[str, ...], min_letters: int) -> tuple[frozenset[str], ...]:
    """Cache only immutable roster-derived combinations, never dataset evidence."""
    owners: dict[str, set[int]] = {}
    for index, name in enumerate(names):
        tokens = _name_tokens(name)
        variants = {" ".join(parts)
                    for size in range(1, len(tokens) + 1)
                    for parts in combinations(tokens, size)}
        for variant in variants:
            owners.setdefault(variant, set()).add(index)
    return tuple(frozenset(
        phrase for phrase, indices in owners.items()
        if indices == {index} and (
            phrase == " ".join(_name_tokens(names[index]))
            or (len(phrase.split()) >= 2 and sum(c.isalpha() for c in phrase) >= min_letters)
        )
    ) for index in range(len(names)))


def _phrase_pattern(phrases: frozenset[str]):
    if not phrases:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(p) for p in sorted(phrases)) + r")(?!\w)")


def _matches_phrase(pattern, text: str) -> bool:
    return pattern is not None and pattern.search(" ".join(_name_tokens(text))) is not None


def _identity_filter(dataset_name: str, name: str, person: Person | None):
    roster = persons_in_dataset(dataset_name)
    matches = person.find_matches(roster) if person is not None else []
    target_indices = ([i for i, candidate in enumerate(roster)
                       if any(candidate is match for match in matches)] if person is not None else
                      [i for i, candidate in enumerate(roster)
                       if _name_tokens(candidate.full_name) == _name_tokens(name)])
    if len(target_indices) == 1:
        index = target_indices[0]
        target = person or roster[index]
    else:
        # Explicit out-of-roster profiling is supported. Duplicate names remain
        # separate owners and therefore cannot produce unique name matches.
        target = person or Person(full_name=name)
        index = len(roster)
        roster = [*roster, target]
    names = tuple(candidate.full_name for candidate in roster)
    config = load_repository_config("people", "dossier")
    phrases = _unique_name_phrases(names, config["minimum_combination_letters"])[index]
    # An enriched display name may differ from the saved roster name. Add its
    # combinations without treating the same person as a competing identity.
    if target.full_name != names[index]:
        enriched = (*names[:index], target.full_name, *names[index + 1:])
        phrases |= _unique_name_phrases(enriched, config["minimum_combination_letters"])[index]
    return target, _phrase_pattern(phrases)


def _scan_person_chunks(dataset_name: str, target: Person, pattern) -> list[Chunk]:
    emails = set(target.email_addresses)
    selected = {}
    for chunk in iter_parsed_chunks(dataset_name):
        filename = PurePath(chunk.document_name.replace("\\", "/")).name
        if (_matches_phrase(pattern, filename) or _matches_phrase(pattern, chunk.text)
                or emails.intersection(extract_email_addresses(chunk.text))
                or (target.linkedin_id and target.linkedin_id in extract_linkedin_ids(chunk.text))):
            selected.setdefault(chunk.chunk_id, chunk)
    return list(selected.values())


async def get_filtered_chunks(
    dataset_name: str, name: str, query: str, *, person: Person | None = None,
) -> list[Chunk]:
    """Scan all current parsed chunks for unique name phrases or exact contacts.

    query is retained for compatibility; selection is now lexical, not semantic.
    As before, synchronization errors propagate rather than implying no evidence.
    """
    target, pattern = _identity_filter(dataset_name, name, person)
    await sync_datasets([slugify(dataset_name)], raise_on_error=True)
    return await asyncio.to_thread(_scan_person_chunks, dataset_name, target, pattern)


async def build_person_dossier(
    dataset_name: str, person_name: str, query: str, *, person: Person | None = None,
) -> Tuple[List[Chunk], List[Chunk]]:
    """
    Retrieves and logically splits parsed chunks into a dedicated 'dossier' (full docs)
    and 'mentions' (isolated chunks), excluding any LinkedIn data.
    """
    logger.info(f"[{dataset_name}] Building dossier for '{person_name}'...")
    dataset_slug = slugify(dataset_name)
    parsed_root = dataset_parsed_path(dataset_slug)
    
    dossier: List[Chunk] = []
    mentions: List[Chunk] = []
    
    _, pattern = _identity_filter(dataset_name, person_name, person)
    filtered_chunks = await get_filtered_chunks(dataset_name, person_name, query, person=person)
    
    if not filtered_chunks:
        return dossier, mentions
        
    # Retain the existing dossier output order.
    filtered_chunks.reverse()
    
    storage = get_storage()
    seen_dossier_docs = set()
    document_texts = {}
    seen_mentions = set()
    
    for c in filtered_chunks:
        doc_name = c.document_name
        
        # Actively exclude LinkedIn data
        if "linkedin" in doc_name.lower():
            continue
            
        # If we already pulled this full document into the dossier, skip processing its chunks
        if doc_name in seen_dossier_docs:
            continue
            
        should_expand = (
            _matches_phrase(pattern, PurePath(doc_name.replace("\\", "/")).name)
            or is_personal_document(doc_name)
        )
        # Chunks retain the original document name. Resolve its parsed path
        # through the same convention used by conversion and indexing.
        full_md_path = parsed_filepath(parsed_root, doc_name)
        
        if should_expand and storage.exists(full_md_path):
            if doc_name not in document_texts:
                document_texts[doc_name] = storage.read_text(full_md_path)
            full_text = document_texts[doc_name]
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
            elif c.chunk_id not in seen_mentions:
                mentions.append(c)
                seen_mentions.add(c.chunk_id)
        elif c.chunk_id not in seen_mentions:
            mentions.append(c)
            seen_mentions.add(c.chunk_id)
            
    logger.info(f"[{dataset_name}] Dossier built: {len(dossier)} full docs, {len(mentions)} mentions.")
    return dossier, mentions
