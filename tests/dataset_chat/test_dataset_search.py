import pytest
from types import SimpleNamespace

from lib.datasets.search import dataset_search
from lib.datasets.source import parsed_filepath


@pytest.mark.asyncio
async def test_dataset_search_embeds_query_and_passes_limit_to_qdrant(mocker):
    mocker.patch("lib.datasets.search.sync_datasets")
    mock_adapter = mocker.patch("lib.datasets.search.QdrantAdapter")
    embedding_service = mocker.patch(
        "lib.datasets.search.EmbeddingService"
    )
    embedding_service.return_value.embed_many = mocker.AsyncMock(
        return_value=[[1.0, 2.0]]
    )
    mock_adapter.return_value.query.return_value = []

    await dataset_search("Avientus", "profile query", max_chunks=25)

    embedding_service.return_value.embed_many.assert_awaited_once_with(
        ["profile query"]
    )
    mock_adapter.return_value.query.assert_called_once_with(
        [1.0, 2.0],
        limit=25,
    )


@pytest.mark.asyncio
async def test_dataset_search_normalizes_ids_from_legacy_and_current_payloads(mocker):
    mocker.patch("lib.datasets.search.sync_datasets")
    mock_adapter = mocker.patch("lib.datasets.search.QdrantAdapter")
    embedding_service = mocker.patch(
        "lib.datasets.search.EmbeddingService"
    )
    embedding_service.return_value.embed_many = mocker.AsyncMock(
        return_value=[[1.0, 2.0]]
    )
    mock_adapter.return_value.query.return_value = [
        SimpleNamespace(
            id="point-id",
            score=0.91,
            payload={
                "chunk_id": "payload-id",
                "document_name": "report.pdf",
                "page_number": 1,
                "last_modified": 1.0,
                "text": "Relevant text",
                "score": None,
            },
        )
    ]

    chunks = await dataset_search("Avientus", "profile query", max_chunks=25)

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "point-id"
    assert chunks[0].score == 0.91


@pytest.mark.asyncio
async def test_dataset_search_can_raise_after_logging_failures(mocker):
    mocker.patch("lib.datasets.search.sync_datasets")
    embedding_service = mocker.patch(
        "lib.datasets.search.EmbeddingService"
    )
    embedding_service.return_value.embed_many = mocker.AsyncMock(
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
