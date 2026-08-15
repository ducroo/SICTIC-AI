import pytest
from types import SimpleNamespace

from lib.datasets.search import dataset_search
from lib.datasets.source import parsed_filepath


def _point(point_id, document_name="report.pdf", score=0.9):
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={
            "chunk_id": f"payload-{point_id}",
            "document_name": document_name,
            "page_number": 1,
            "last_modified": 1.0,
            "text": f"Text for {point_id}",
            "score": None,
        },
    )


@pytest.fixture
def search_backend(mocker):
    """Patch sync, embeddings, and Qdrant for dataset_search unit tests."""
    mocker.patch("lib.datasets.search.sync_datasets")
    adapter = mocker.patch("lib.datasets.search.QdrantAdapter")
    embedding_service = mocker.patch("lib.datasets.search.EmbeddingService")
    embedding_service.return_value.embed_many = mocker.AsyncMock(
        return_value=[[1.0, 2.0]]
    )
    adapter.return_value.sparse_enabled.return_value = True
    adapter.return_value.query_hybrid.return_value = []
    adapter.return_value.query.return_value = []
    return SimpleNamespace(adapter=adapter, embeddings=embedding_service)


@pytest.mark.asyncio
async def test_dataset_search_fuses_dense_and_sparse_over_candidate_pool(
    search_backend,
):
    await dataset_search("Avientus", "patent assignment", max_chunks=25)

    search_backend.embeddings.return_value.embed_many.assert_awaited_once_with(
        ["patent assignment"]
    )
    search_backend.adapter.return_value.query.assert_not_called()
    call = search_backend.adapter.return_value.query_hybrid.call_args
    assert call.args[0] == [1.0, 2.0]
    # BM25 terms are derived from the query text, not the embedding.
    assert call.args[1].indices
    # Retrieval runs wider than the requested chunk count so that reranking
    # and the per-document cap have candidates to work with.
    assert call.kwargs["limit"] == 100


@pytest.mark.asyncio
async def test_dataset_search_falls_back_to_dense_for_legacy_collections(
    search_backend,
):
    search_backend.adapter.return_value.sparse_enabled.return_value = False

    await dataset_search("Avientus", "profile query", max_chunks=25)

    search_backend.adapter.return_value.query_hybrid.assert_not_called()
    search_backend.adapter.return_value.query.assert_called_once_with(
        [1.0, 2.0],
        limit=100,
    )


@pytest.mark.asyncio
async def test_dataset_search_normalizes_ids_from_legacy_and_current_payloads(
    search_backend,
):
    search_backend.adapter.return_value.query_hybrid.return_value = [
        _point("point-id", score=0.91)
    ]

    chunks = await dataset_search("Avientus", "profile query", max_chunks=25)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "point-id"
    assert chunks[0].score == 0.91


@pytest.mark.asyncio
async def test_dataset_search_caps_one_document_from_filling_the_result(
    search_backend,
):
    search_backend.adapter.return_value.query_hybrid.return_value = [
        _point(f"big-{index}", document_name="master-agreement.pdf")
        for index in range(6)
    ] + [
        _point("other-1", document_name="cap-table.xlsx"),
        _point("other-2", document_name="patent-register.pdf"),
    ]

    chunks = await dataset_search("Avientus", "ownership", max_chunks=4)

    documents = [chunk.document_name for chunk in chunks]
    assert len(chunks) == 4
    assert documents.count("master-agreement.pdf") == 2
    assert "cap-table.xlsx" in documents
    assert "patent-register.pdf" in documents


@pytest.mark.asyncio
async def test_dataset_search_keeps_requested_count_when_one_document_matches(
    search_backend,
):
    search_backend.adapter.return_value.query_hybrid.return_value = [
        _point(f"only-{index}", document_name="single.pdf")
        for index in range(5)
    ]

    chunks = await dataset_search("Avientus", "ownership", max_chunks=4)

    assert len(chunks) == 4


@pytest.mark.asyncio
async def test_dataset_search_applies_reranked_order(search_backend, mocker):
    search_backend.adapter.return_value.query_hybrid.return_value = [
        _point("first", document_name="a.pdf"),
        _point("second", document_name="b.pdf"),
    ]
    mocker.patch(
        "lib.datasets.search.rerank_chunks",
        new=mocker.AsyncMock(side_effect=lambda _query, chunks: chunks[::-1]),
    )

    chunks = await dataset_search("Avientus", "profile query", max_chunks=2)

    assert [chunk.chunk_id for chunk in chunks] == ["second", "first"]


@pytest.mark.asyncio
async def test_dataset_search_can_raise_after_logging_failures(
    search_backend,
    mocker,
):
    search_backend.embeddings.return_value.embed_many = mocker.AsyncMock(
        side_effect=RuntimeError("embedding service unavailable")
    )
    logged = mocker.patch("lib.datasets.search.logger.exception")

    with pytest.raises(RuntimeError, match="Semantic search failed"):
        await dataset_search(
            "Avientus",
            "profile query",
            max_chunks=25,
            raise_on_error=True,
        )

    logged.assert_called_once()


def test_parsed_filepath_keeps_markdown_source_name():
    assert parsed_filepath("docling_data/datasets2md/generated/person-profile/datasets", "urs-gubser.md") == (
        "docling_data/datasets2md/generated/person-profile/datasets/urs-gubser.md"
    )
    assert parsed_filepath("docling_data/datasets2md/startups/avientus/datasets", "deck.pdf") == (
        "docling_data/datasets2md/startups/avientus/datasets/deck.pdf.md"
    )
