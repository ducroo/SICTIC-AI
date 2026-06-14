from types import SimpleNamespace

from skills.dataset_chat import dataset_delete as dataset_delete_module


def test_orphaned_collections_compare_against_all_present_datasets(mocker):
    mocker.patch.object(dataset_delete_module, "embedding_model", return_value="ollama/test:8b")
    mocker.patch.object(dataset_delete_module, "iter_domains", return_value=["startups", "community"])
    mocker.patch.object(
        dataset_delete_module,
        "list_dataset_names",
        side_effect=lambda domain: {
            "startups": ["active-startup", "inactive-startup"],
            "community": ["sictic-members"],
        }[domain],
    )
    client_class = mocker.patch.object(dataset_delete_module, "QdrantClient")
    client_class.return_value.get_collections.return_value.collections = [
        SimpleNamespace(name="active-startup-test-8b"),
        SimpleNamespace(name="inactive-startup-test-8b"),
        SimpleNamespace(name="sictic-members-test-8b"),
        SimpleNamespace(name="removed-dataset-test-8b"),
        SimpleNamespace(name="removed-dataset-other-model"),
    ]

    assert dataset_delete_module.orphaned_qdrant_collections() == [
        "removed-dataset-test-8b"
    ]


def test_prune_orphaned_collections_is_dry_run_by_default(mocker):
    mocker.patch.object(
        dataset_delete_module,
        "orphaned_qdrant_collections",
        return_value=["removed-dataset-test-8b"],
    )
    client_class = mocker.patch.object(dataset_delete_module, "QdrantClient")

    result = dataset_delete_module.prune_orphaned_qdrant_collections()

    assert result == ["removed-dataset-test-8b"]
    client_class.assert_not_called()


def test_prune_orphaned_collections_deletes_when_applied(mocker):
    mocker.patch.object(
        dataset_delete_module,
        "orphaned_qdrant_collections",
        return_value=["removed-a-test-8b", "removed-b-test-8b"],
    )
    client_class = mocker.patch.object(dataset_delete_module, "QdrantClient")

    result = dataset_delete_module.prune_orphaned_qdrant_collections(apply=True)

    assert result == ["removed-a-test-8b", "removed-b-test-8b"]
    assert [
        call.args[0]
        for call in client_class.return_value.delete_collection.call_args_list
    ] == ["removed-a-test-8b", "removed-b-test-8b"]
