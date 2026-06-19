from skills.dataset_maintenance import maintenance


class FakeAdmin:
    def __init__(self, collections):
        self.collections = collections
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
    admin = FakeAdmin(
        [
            "active-startup-test-8b",
            "inactive-startup-test-8b",
            "sictic-members-test-8b",
            "removed-dataset-test-8b",
            "removed-dataset-other-model",
        ]
    )

    assert maintenance.orphaned_qdrant_collections(admin=admin) == [
        "removed-dataset-test-8b"
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
    admin = FakeAdmin(["removed-dataset-test-8b"])

    result = maintenance.prune_orphaned_qdrant_collections(admin=admin)

    assert result == ["removed-dataset-test-8b"]
    assert admin.deleted == []


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
    admin = FakeAdmin(["removed-a-test-8b", "removed-b-test-8b"])

    result = maintenance.prune_orphaned_qdrant_collections(
        apply=True,
        admin=admin,
    )

    assert result == ["removed-a-test-8b", "removed-b-test-8b"]
    assert admin.deleted == result
