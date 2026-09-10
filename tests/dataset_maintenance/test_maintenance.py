from lib.datasets.manifest import IngestionManifest
from lib.storage import LocalStorage
from skills.dataset_maintenance import maintenance


class FakeAdapter:
    collection_name = "sictic-ai-datasets-test-8b"

    def __init__(self, datasets):
        self.datasets = datasets
        self.deleted = []

    def list_indexed_datasets(self):
        return list(self.datasets)

    def delete_dataset(self, dataset):
        self.deleted.append(dataset)
        return True


class FakeAdmin:
    def __init__(self, collections):
        self.collections = list(collections)
        self.deleted = []

    def list_collections(self):
        return list(self.collections)

    def delete_collection(self, collection):
        self.deleted.append(collection)


def test_orphaned_collections_compare_against_present_datasets(mocker):
    mocker.patch.object(
        maintenance,
        "embedding_model",
        return_value="ollama/test:8b",
    )
    mocker.patch.object(
        maintenance,
        "list_all_dataset_names",
        return_value=[
            "active-startup",
            "inactive-startup",
            "sictic-members",
        ],
    )
    adapter = FakeAdapter(
        [
            "active-startup",
            "inactive-startup",
            "sictic-members",
            "removed-dataset",
        ]
    )

    assert maintenance.orphaned_qdrant_collections(adapter=adapter) == [
        "removed-dataset",
    ]


def test_prune_orphaned_collections_is_dry_run_by_default(mocker):
    mocker.patch.object(
        maintenance,
        "embedding_model",
        return_value="ollama/test:8b",
    )
    mocker.patch.object(
        maintenance,
        "list_all_dataset_names",
        return_value=[],
    )
    adapter = FakeAdapter(["removed-dataset"])

    result = maintenance.prune_orphaned_qdrant_collections(adapter=adapter)

    assert result == ["removed-dataset"]
    assert adapter.deleted == []


def test_prune_orphaned_collections_deletes_when_applied(mocker):
    mocker.patch.object(
        maintenance,
        "embedding_model",
        return_value="ollama/test:8b",
    )
    mocker.patch.object(
        maintenance,
        "list_all_dataset_names",
        return_value=[],
    )
    adapter = FakeAdapter(["removed-a", "removed-b"])

    result = maintenance.prune_orphaned_qdrant_collections(
        apply=True,
        adapter=adapter,
    )

    assert result == ["removed-a", "removed-b"]
    assert adapter.deleted == result


def _write_indexed_manifest(storage, parsed_path, model):
    manifest = IngestionManifest(storage, parsed_path)
    manifest.documents = {
        "report.md": {
            "indexed_parsed_sha256": "parsed",
            "indexed_chunker_version": "chunker",
            "indexed_embedding_model": model,
            "indexed_sparse_version": "bm25-v1",
        }
    }
    manifest.indexed_dataset_revision = "revision"
    manifest.save()


def test_delete_dataset_embedding_resets_matching_manifest(tmp_path, mocker):
    storage = LocalStorage(tmp_path)
    parsed_path = "parsed/example"
    _write_indexed_manifest(storage, parsed_path, "ollama/test:8b")
    adapter = mocker.Mock()
    adapter.collection_name = "sictic-ai-datasets-test-8b"
    adapter.delete_dataset.return_value = True
    mocker.patch.object(maintenance, "QdrantAdmin")
    mocker.patch.object(maintenance, "QdrantAdapter", return_value=adapter)
    mocker.patch.object(maintenance, "get_storage", return_value=storage)
    mocker.patch.object(
        maintenance,
        "dataset_parsed_path",
        return_value=parsed_path,
    )

    deleted = maintenance.delete_dataset_index(
        "example",
        "ollama/test:8b",
    )

    assert deleted == ["sictic-ai-datasets-test-8b"]
    state = IngestionManifest.load(storage, parsed_path).documents["report.md"]
    assert "indexed_parsed_sha256" not in state
    assert "indexed_embedding_model" not in state


def test_delete_embedding_collection_resets_all_matching_manifests(
    tmp_path,
    mocker,
):
    storage = LocalStorage(tmp_path)
    _write_indexed_manifest(storage, "parsed/first", "ollama/test:8b")
    _write_indexed_manifest(storage, "parsed/second", "other/model:1b")
    admin = FakeAdmin(["sictic-ai-datasets-test-8b"])
    mocker.patch.object(maintenance, "QdrantAdmin", return_value=admin)
    mocker.patch.object(maintenance, "get_storage", return_value=storage)
    mocker.patch.object(
        maintenance,
        "list_all_dataset_names",
        return_value=["first", "second"],
    )
    mocker.patch.object(
        maintenance,
        "dataset_parsed_path",
        side_effect=lambda dataset: f"parsed/{dataset}",
    )

    deleted = maintenance.delete_dataset_index(
        embeddings="ollama/test:8b",
    )

    assert deleted == ["sictic-ai-datasets-test-8b"]
    first = IngestionManifest.load(storage, "parsed/first")
    second = IngestionManifest.load(storage, "parsed/second")
    assert "indexed_embedding_model" not in first.documents["report.md"]
    assert (
        second.documents["report.md"]["indexed_embedding_model"]
        == "other/model:1b"
    )
