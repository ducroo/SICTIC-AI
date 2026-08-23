from types import SimpleNamespace

import pytest

from lib import ephemeral_dataset


@pytest.mark.asyncio
async def test_ephemeral_cleanup_keeps_dataset_visible_for_adapter(mocker):
    events = []
    storage = mocker.Mock()
    storage.rmtree.side_effect = lambda path: events.append(("rmtree", path))
    storage.mkdir.side_effect = lambda path: events.append(("mkdir", path))
    adapter = mocker.Mock()
    adapter.delete_dataset.side_effect = lambda: events.append(("delete", None))

    def create_adapter(dataset):
        events.append(("adapter", dataset))
        return adapter

    async def fake_sync(datasets, **_kwargs):
        events.append(("sync", datasets))

    mocker.patch.object(ephemeral_dataset, "get_storage", return_value=storage)
    mocker.patch.object(
        ephemeral_dataset,
        "dataset_location_for_domain",
        return_value=SimpleNamespace(
            raw_rel="generated/temp/datasets",
            parsed_rel="parsed/temp",
        ),
    )
    mocker.patch.object(ephemeral_dataset, "QdrantAdapter", side_effect=create_adapter)
    mocker.patch.object(ephemeral_dataset, "sync_datasets", side_effect=fake_sync)

    result = await ephemeral_dataset.prepare_ephemeral_dataset([], "temp")

    assert result == "temp"
    assert events[:4] == [
        ("adapter", "temp"),
        ("delete", None),
        ("rmtree", "generated/temp/datasets"),
        ("rmtree", "parsed/temp"),
    ]
