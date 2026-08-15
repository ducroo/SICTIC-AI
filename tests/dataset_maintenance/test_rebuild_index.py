import pytest

from lib.datasets.manifest import IngestionManifest
from lib.storage import LocalStorage
from skills.dataset_maintenance import maintenance


class FakeAdmin:
    def __init__(self, collections):
        self.collections = collections
        self.deleted = []

    def list_collections(self):
        return list(self.collections)

    def delete_collection(self, collection):
        self.deleted.append(collection)


def _prepare(tmp_path, mocker, collections, documents):
    storage = LocalStorage(tmp_path)
    parsed_rel = "cache/datasets2md/example"
    manifest = IngestionManifest(storage, parsed_rel)
    manifest.documents = documents
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()

    admin = FakeAdmin(collections)
    mocker.patch.object(maintenance, "QdrantAdmin", return_value=admin)
    mocker.patch.object(maintenance, "get_storage", return_value=storage)
    mocker.patch.object(
        maintenance,
        "dataset_parsed_path",
        return_value=parsed_rel,
    )
    return storage, parsed_rel, admin


def test_rebuild_drops_the_collection_and_clears_index_checkpoints(
    tmp_path,
    mocker,
):
    storage, parsed_rel, admin = _prepare(
        tmp_path,
        mocker,
        collections=["example-test-embedding-8b"],
        documents={
            "report.md": {
                "source_sha256": "source",
                "parsed_sha256": "parsed",
                "parser_version": "docling",
                "indexed_parsed_sha256": "parsed",
                "indexed_chunker_version": "chunker",
                "indexed_embedding_model": "model",
            }
        },
    )

    rebuild = maintenance.rebuild_dataset_index("Example")

    assert rebuild.dataset == "example"
    assert rebuild.collection_deleted is True
    assert rebuild.documents_reset == 1
    assert admin.deleted == ["example-test-embedding-8b"]

    state = IngestionManifest.load(storage, parsed_rel).documents["report.md"]
    # Parsing checkpoints survive so a rebuild re-embeds without re-parsing.
    assert state["parsed_sha256"] == "parsed"
    assert "indexed_parsed_sha256" not in state
    assert "indexed_embedding_model" not in state


def test_rebuild_reports_a_missing_collection_without_failing(tmp_path, mocker):
    _storage, _parsed_rel, admin = _prepare(
        tmp_path,
        mocker,
        collections=[],
        documents={"report.md": {"indexed_parsed_sha256": "parsed"}},
    )

    rebuild = maintenance.rebuild_dataset_index("example")

    assert rebuild.collection_deleted is False
    assert admin.deleted == []
    assert rebuild.documents_reset == 1


def test_rebuild_ignores_documents_that_were_never_indexed(tmp_path, mocker):
    storage, parsed_rel, _admin = _prepare(
        tmp_path,
        mocker,
        collections=[],
        documents={"report.md": {"parsed_sha256": "parsed"}},
    )

    rebuild = maintenance.rebuild_dataset_index("example")

    assert rebuild.documents_reset == 0
    assert (
        IngestionManifest.load(storage, parsed_rel).indexed_dataset_revision
        == "revision-1"
    )


def test_rebuild_requires_a_dataset():
    with pytest.raises(ValueError, match="--dataset"):
        maintenance.rebuild_dataset_index("")
