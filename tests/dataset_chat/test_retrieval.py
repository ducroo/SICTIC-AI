import pytest

from lib.datasets.models import Chunk
from lib.datasets.retrieval import (
    apply_document_diversity,
    candidate_limit,
    max_chunks_per_document,
)


def _chunk(chunk_id: str, document_name: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_name=document_name,
        page_number=1,
        last_modified=0.0,
        text=f"text {chunk_id}",
    )


def test_candidate_limit_oversamples_by_default():
    assert candidate_limit(25) == 100


def test_candidate_limit_honours_configured_multiplier(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CANDIDATE_MULTIPLIER", "2")

    assert candidate_limit(25) == 50


def test_candidate_limit_never_returns_fewer_than_requested(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CANDIDATE_MULTIPLIER", "0.1")

    assert candidate_limit(25) == 25


def test_candidate_limit_ignores_invalid_configuration(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CANDIDATE_MULTIPLIER", "not-a-number")

    assert candidate_limit(25) == 100


def test_candidate_limit_is_bounded():
    assert candidate_limit(1000) == 400


@pytest.mark.parametrize(
    ("share", "expected"),
    [("0.4", 10), ("0.2", 5), ("0", 25), ("1", 25)],
)
def test_max_chunks_per_document_follows_share(monkeypatch, share, expected):
    monkeypatch.setenv("RETRIEVAL_MAX_DOCUMENT_SHARE", share)

    assert max_chunks_per_document(25) == expected


def test_max_chunks_per_document_is_at_least_one(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MAX_DOCUMENT_SHARE", "0.1")

    assert max_chunks_per_document(4) == 1


def test_diversity_demotes_chunks_beyond_the_document_cap():
    chunks = [_chunk(f"a{index}", "big.pdf") for index in range(4)]
    chunks += [_chunk("b1", "small.pdf")]

    selected = apply_document_diversity(chunks, limit=3, max_per_document=2)

    assert [chunk.chunk_id for chunk in selected] == ["a0", "a1", "b1"]


def test_diversity_backfills_rather_than_returning_fewer_chunks():
    chunks = [_chunk(f"a{index}", "only.pdf") for index in range(5)]

    selected = apply_document_diversity(chunks, limit=4, max_per_document=2)

    assert [chunk.chunk_id for chunk in selected] == ["a0", "a1", "a2", "a3"]


def test_diversity_preserves_order_when_cap_is_not_binding():
    chunks = [_chunk("a1", "one.pdf"), _chunk("b1", "two.pdf")]

    selected = apply_document_diversity(chunks, limit=5, max_per_document=5)

    assert selected == chunks


def test_diversity_returns_nothing_for_a_zero_limit():
    assert apply_document_diversity([_chunk("a1", "one.pdf")], 0, 1) == []
