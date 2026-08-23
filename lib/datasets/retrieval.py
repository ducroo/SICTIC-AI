"""Candidate sizing and result diversification for dataset search."""

from __future__ import annotations

import os
from collections import Counter

from lib.datasets.models import Chunk
from lib.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_CANDIDATE_MULTIPLIER = 4.0
_DEFAULT_DOCUMENT_SHARE = 0.4
_MAX_CANDIDATES = 400


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r.", name, raw)
        return default


def candidate_limit(max_chunks: int) -> int:
    """Number of chunks to retrieve before reranking and diversification."""
    multiplier = max(1.0, _env_float(
        "RETRIEVAL_CANDIDATE_MULTIPLIER",
        _DEFAULT_CANDIDATE_MULTIPLIER,
    ))
    return min(_MAX_CANDIDATES, max(max_chunks, int(max_chunks * multiplier)))


def max_chunks_per_document(max_chunks: int) -> int:
    """Cap on how many of the returned chunks one document may contribute."""
    share = _env_float(
        "RETRIEVAL_MAX_DOCUMENT_SHARE",
        _DEFAULT_DOCUMENT_SHARE,
    )
    if share <= 0 or share >= 1:
        return max_chunks
    return max(1, round(max_chunks * share))


def apply_document_diversity(
    chunks: list[Chunk],
    limit: int,
    max_per_document: int,
) -> list[Chunk]:
    """Stop one large document from crowding out the rest of a data room.

    Chunks above the per-document cap are demoted rather than dropped, so the
    caller still receives as many chunks as were retrieved.
    """
    if limit <= 0:
        return []
    if max_per_document >= limit:
        return chunks[:limit]

    selected: list[Chunk] = []
    demoted: list[Chunk] = []
    per_document: Counter[str] = Counter()
    for chunk in chunks:
        if per_document[chunk.document_name] < max_per_document:
            per_document[chunk.document_name] += 1
            selected.append(chunk)
        else:
            demoted.append(chunk)

    results = selected[:limit]
    if len(results) < limit:
        results.extend(demoted[:limit - len(results)])
    return results
