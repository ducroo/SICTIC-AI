import pytest

from skills.dataset_chat.dataset_search import dataset_search
from skills.dataset_chat.core.ingestion import _parsed_filepath


@pytest.mark.asyncio
async def test_dataset_search_defaults_threshold_when_max_chunks_is_provided(mocker):
    mocker.patch("skills.dataset_chat.dataset_search.sync_datasets")
    mock_adapter = mocker.patch("skills.dataset_chat.dataset_search.QdrantAdapter")

    async def search(*args, **kwargs):
        return []

    mock_adapter.return_value.search.side_effect = search

    await dataset_search("Avientus", "profile query", max_chunks=25)

    mock_adapter.return_value.search.assert_called_once_with(
        "profile query",
        limit=25,
        threshold_factor=0.8,
    )


def test_parsed_filepath_keeps_markdown_source_name():
    assert _parsed_filepath("storage/datasets2md/community/person-profile/datasets", "urs-gubser.md") == (
        "storage/datasets2md/community/person-profile/datasets/urs-gubser.md"
    )
    assert _parsed_filepath("storage/datasets2md/startups/avientus/datasets", "deck.pdf") == (
        "storage/datasets2md/startups/avientus/datasets/deck.pdf.md"
    )
