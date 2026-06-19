from types import SimpleNamespace

import pytest

from lib.datasets import ingestion
from lib.datasets.models import IngestionResult
from lib.datasets.source import SourceDocument


@pytest.mark.asyncio
async def test_single_dataset_runs_conversion_before_indexing_with_shared_state(
    mocker,
):
    storage = SimpleNamespace(
        refresh=mocker.Mock(),
        exists=mocker.Mock(return_value=True),
    )
    sources = [
        SourceDocument(
            filename="report.pdf",
            mtime=1.0,
            sha256="source-sha",
        )
    ]
    manifest = object()
    events = []

    mocker.patch.object(ingestion, "get_storage", return_value=storage)
    mocker.patch.object(
        ingestion,
        "dataset_raw_path",
        return_value="datasets/example",
    )
    mocker.patch.object(
        ingestion,
        "dataset_parsed_path",
        return_value="cache/example",
    )
    mocker.patch.object(
        ingestion,
        "snapshot_source_files",
        return_value=sources,
    )
    mocker.patch.object(
        ingestion.IngestionManifest,
        "load",
        return_value=manifest,
    )

    async def convert(*_args, **kwargs):
        events.append(("conversion", kwargs))

    async def index(*_args, **kwargs):
        events.append(("indexing", kwargs))

    mocker.patch.object(
        ingestion,
        "reconcile_conversions",
        side_effect=convert,
    )
    mocker.patch.object(
        ingestion,
        "reconcile_index",
        side_effect=index,
    )

    result = await ingestion._sync_single_dataset("example")

    assert isinstance(result, IngestionResult)
    assert [event[0] for event in events] == ["conversion", "indexing"]
    for _stage, kwargs in events:
        assert kwargs["sources"] is sources
        assert kwargs["manifest"] is manifest
        assert kwargs["result"] is result
