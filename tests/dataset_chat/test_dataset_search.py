import pytest

from skills.dataset_chat.dataset_search import dataset_search


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
