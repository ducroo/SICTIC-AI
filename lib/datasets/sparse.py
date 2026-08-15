"""BM25 sparse vector encoding for hybrid retrieval.

Qdrant applies the inverse document frequency through the IDF modifier on the
sparse vector configuration, so only the term-frequency component of BM25 is
encoded here. Token identifiers are content hashes, which keeps the encoder
stateless and therefore consistent across processes and machines.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

SPARSE_ENCODER_VERSION = "bm25-v1"

_K1 = 1.2
_B = 0.75
# Reference document length in tokens used for BM25 length normalization.
# Chunks are capped at 1000 characters, which averages out near this value.
_AVERAGE_DOCUMENT_TOKENS = 120.0

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
_MIN_TOKEN_LENGTH = 2
_MAX_TOKEN_LENGTH = 40

# Function words carry almost no retrieval signal. Qdrant's IDF modifier would
# already downweight them; dropping them here keeps the sparse index smaller.
_STOPWORDS = frozenset(
    """
    a an and are as at be been but by for from had has have he her his if in
    into is it its of on or she that the their them there these they this to
    was were which who will with would you your
    aber alle als am auch auf aus bei bin bis das dass dem den der des die dies
    ein eine einer eines er es fuer für hat haben ich ihre im ist mit nach nicht
    noch nur oder sich sie sind über und uns vom von vor war werden wie wir zu
    zum zur
    au aux avec ce ces dans de des du elle en est et il la le les leur mais ne
    nous ou par pas pour que qui sa se ses son sur un une vous
    """.split()
)


@dataclass(frozen=True)
class SparseVectorData:
    """Sparse vector as parallel index and value lists, sorted by index."""

    indices: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.indices)


def tokenize(text: str) -> list[str]:
    """Split text into lowercase content tokens."""
    tokens = []
    for token in _TOKEN_PATTERN.findall(text.lower()):
        if not _MIN_TOKEN_LENGTH <= len(token) <= _MAX_TOKEN_LENGTH:
            continue
        if token in _STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def token_id(token: str) -> int:
    """Map a token to a stable unsigned 32-bit sparse vector index."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big")


def _to_sparse_vector(weights: dict[int, float]) -> SparseVectorData:
    if not weights:
        return SparseVectorData()
    indices = sorted(weights)
    return SparseVectorData(
        indices=indices,
        values=[weights[index] for index in indices],
    )


def encode_document(text: str) -> SparseVectorData:
    """Encode indexed text as BM25 term-frequency weights."""
    tokens = tokenize(text)
    if not tokens:
        return SparseVectorData()

    length_penalty = _K1 * (
        1 - _B + _B * len(tokens) / _AVERAGE_DOCUMENT_TOKENS
    )
    weights: dict[int, float] = {}
    for token, frequency in Counter(tokens).items():
        weight = frequency * (_K1 + 1) / (frequency + length_penalty)
        index = token_id(token)
        weights[index] = weights.get(index, 0.0) + weight
    return _to_sparse_vector(weights)


def encode_query(text: str) -> SparseVectorData:
    """Encode a query as unit weights over its distinct tokens."""
    weights = {token_id(token): 1.0 for token in tokenize(text)}
    return _to_sparse_vector(weights)
