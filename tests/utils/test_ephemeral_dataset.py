from types import SimpleNamespace

import pytest

from lib import ephemeral_dataset
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage


@pytest.mark.asyncio
async def test_ephemeral_cleanup_keeps_dataset_visible_for_adapter(mocker):
    events = []
    storage = mocker.Mock()
    storage.exists.return_value = False
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
            slug="temp",
            raw_rel="generated/temp/datasets",
            insights_rel="generated/temp/insights",
            parsed_rel="parsed/temp/datasets",
            dataset_root="generated",
            insights_root="generated",
            parsed_root="parsed",
        ),
    )
    mocker.patch.object(ephemeral_dataset, "find_dataset_location", return_value=None)
    mocker.patch.object(ephemeral_dataset, "QdrantAdapter", side_effect=create_adapter)
    mocker.patch.object(ephemeral_dataset, "sync_datasets", side_effect=fake_sync)

    result = await ephemeral_dataset.prepare_ephemeral_dataset([], "temp")

    assert result == "temp"
    assert events[:4] == [
        ("adapter", "temp"),
        ("delete", None),
        ("rmtree", "generated/temp"),
        ("rmtree", "parsed/temp"),
    ]


@pytest.mark.asyncio
async def test_preparing_again_removes_entire_previous_investigation(mock_env, mocker, tmp_path):
    storage = get_storage()
    location = dataset_location_for_domain("temp_review", "generated")
    old_files = [
        f"{location.raw_rel}/old.md",
        f"{location.insights_rel}/startup-sector-temp-review-manual.json",
        f"{location.insights_rel}/startup-sector-temp-review-test.json",
        f"{location.dataset_root}/{location.slug}/.manifest.json",
        f"{location.parsed_rel}/old.md",
    ]
    for path in old_files:
        storage.write_text(path, "old investigation")
    preserved = []
    for domain in ("generated", "startups", "community"):
        other = dataset_location_for_domain(f"other-{domain}", domain)
        path = f"{other.raw_rel}/keep.md"
        storage.write_text(path, "keep")
        preserved.append(path)
    source = tmp_path / "new.md"
    source.write_text("new evidence")
    adapter = mocker.patch.object(ephemeral_dataset, "QdrantAdapter")
    sync = mocker.patch.object(ephemeral_dataset, "sync_datasets", new_callable=mocker.AsyncMock)

    result = await ephemeral_dataset.prepare_ephemeral_dataset([str(source)], "temp_review")

    assert result == "temp_review"  # Preserve the caller-facing name contract.
    adapter.assert_called_once_with("temp_review")
    adapter.return_value.delete_dataset.assert_called_once_with()
    sync.assert_awaited_once_with(["temp_review"], raise_on_error=True)
    assert all(not storage.exists(path) for path in old_files)
    assert storage.read_text(f"{location.raw_rel}/new.md") == "new evidence"
    assert all(storage.read_text(path) == "keep" for path in preserved)


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["startups", "community"])
async def test_cannot_reset_permanent_dataset(mock_env, mocker, domain):
    storage = get_storage()
    location = dataset_location_for_domain("permanent", domain)
    source = f"{location.raw_rel}/keep.md"
    storage.write_text(source, "keep")
    adapter = mocker.patch.object(ephemeral_dataset, "QdrantAdapter")
    sync = mocker.patch.object(ephemeral_dataset, "sync_datasets", new_callable=mocker.AsyncMock)

    with pytest.raises(ValueError, match="Cannot reset permanent dataset"):
        await ephemeral_dataset.prepare_ephemeral_dataset([], "permanent")

    assert storage.read_text(source) == "keep"
    adapter.assert_not_called()
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_cleanup_failure_preserves_previous_files(mock_env, mocker):
    storage = get_storage()
    location = dataset_location_for_domain("temp", "generated")
    source = f"{location.raw_rel}/old.md"
    insight = f"{location.insights_rel}/old-manual.md"
    for path in (source, insight):
        storage.write_text(path, "keep")
    adapter = mocker.patch.object(ephemeral_dataset, "QdrantAdapter")
    adapter.return_value.delete_dataset.side_effect = RuntimeError("index unavailable")
    sync = mocker.patch.object(ephemeral_dataset, "sync_datasets", new_callable=mocker.AsyncMock)

    with pytest.raises(RuntimeError, match="index unavailable"):
        await ephemeral_dataset.prepare_ephemeral_dataset([], "temp")

    assert storage.read_text(source) == "keep"
    assert storage.read_text(insight) == "keep"
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_name_cannot_reset_generated_root(mock_env, mocker):
    adapter = mocker.patch.object(ephemeral_dataset, "QdrantAdapter")
    with pytest.raises(ValueError, match="nonempty name"):
        await ephemeral_dataset.prepare_ephemeral_dataset([], "")
    adapter.assert_not_called()


@pytest.mark.asyncio
async def test_failed_directory_removal_stops_ingestion(mock_env, mocker):
    storage = get_storage()
    location = dataset_location_for_domain("temp", "generated")
    source = f"{location.raw_rel}/old.md"
    storage.write_text(source, "old evidence")
    mocker.patch.object(ephemeral_dataset, "QdrantAdapter")
    mocker.patch.object(storage, "rmtree")
    sync = mocker.patch.object(ephemeral_dataset, "sync_datasets", new_callable=mocker.AsyncMock)

    with pytest.raises(OSError, match="Could not clear temporary dataset directory"):
        await ephemeral_dataset.prepare_ephemeral_dataset([], "temp")

    sync.assert_not_awaited()
