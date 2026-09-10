"""Live check that BM25 fusion recovers exact-term hits dense search misses."""

import pytest

from lib.infrastructure.qdrant import QdrantAdapter, QdrantAdmin
from lib.datasets.chunking import split_markdown
from lib.datasets.indexing import replace_document
from lib.datasets.sparse import encode_query

DATASET = "sictic-live-hybrid-test"
QUERY_VECTOR = [1.0, 0.0, 0.0, 0.0]
EXACT_TERM = "Inventionsabtretungserklärung"

DOCUMENTS = {
    # Steered onto the query vector, so dense search ranks it first.
    "share-purchase-agreement.pdf":
        "The parties agree on the transfer of shares and closing. " * 5,
    # Holds the exact term but is orthogonal to the query vector.
    "patent-register.pdf":
        f"IPI extract. {EXACT_TERM} signed under Art. 332 OR. " * 5,
    "cap-table.xlsx":
        "Founder holdings and option pool allocation. " * 5,
}


class _SteeredEmbeddings:
    """Dense vectors chosen so dense-only search ranks the wrong document."""

    model = "live-hybrid-test"

    @staticmethod
    def _vector(text: str) -> list[float]:
        if "shares" in text:
            return [1.0, 0.0, 0.0, 0.0]
        if EXACT_TERM in text:
            return [0.0, 1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0, 0.0]

    async def embed_many(self, texts):
        return [self._vector(text) for text in texts]

    async def vector_size(self) -> int:
        return 4


@pytest.fixture
def hybrid_collection():
    try:
        adapter = QdrantAdapter(
            DATASET,
            vector_size=4,
            embeddings_model=_SteeredEmbeddings.model,
        )
    except Exception as error:
        pytest.skip(f"Qdrant unavailable: {error}")
    yield adapter
    QdrantAdmin().delete_collection(adapter.collection_name)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bm25_branch_recovers_exact_term_matches(hybrid_collection):
    assert hybrid_collection.sparse_enabled()

    embeddings = _SteeredEmbeddings()
    for name, text in DOCUMENTS.items():
        await replace_document(
            hybrid_collection,
            embeddings,
            name,
            split_markdown(text, name, 1.0),
            with_sparse=True,
        )

    dense = [
        point.payload["document_name"]
        for point in hybrid_collection.query(QUERY_VECTOR, limit=3)
    ]
    hybrid = [
        point.payload["document_name"]
        for point in hybrid_collection.query_hybrid(
            QUERY_VECTOR,
            encode_query(EXACT_TERM),
            limit=3,
            candidate_limit=20,
        )
    ]

    assert dense[0] == "share-purchase-agreement.pdf"
    assert dense.index("patent-register.pdf") == 2
    assert hybrid[0] == "patent-register.pdf"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_hybrid_falls_back_when_no_term_matches(hybrid_collection):
    embeddings = _SteeredEmbeddings()
    for name, text in DOCUMENTS.items():
        await replace_document(
            hybrid_collection,
            embeddings,
            name,
            split_markdown(text, name, 1.0),
            with_sparse=True,
        )

    results = hybrid_collection.query_hybrid(
        QUERY_VECTOR,
        encode_query("zzzznonexistentterm"),
        limit=3,
        candidate_limit=20,
    )

    assert [point.payload["document_name"] for point in results]
