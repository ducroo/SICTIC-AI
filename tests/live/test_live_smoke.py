import os

import pytest
from lib.storage_domains import dataset_raw_path, list_dataset_names


def _discover_dataset(storage):
    items = list_dataset_names("startups") + list_dataset_names("community")
    active = [
        item for item in items
        if storage.exists(f"{dataset_raw_path(item)}/__active_dataset__")
    ]
    candidates = active or items
    return candidates[0] if candidates else None


@pytest.mark.live
def test_live_storage_discovers_dataset():
    from lib.storage import get_storage, reset_storage_singleton

    reset_storage_singleton()
    storage = get_storage()
    dataset = _discover_dataset(storage)

    if not dataset:
        pytest.skip("No dataset available in configured storage.")
    assert storage.is_dir(dataset_raw_path(dataset))


@pytest.mark.live
def test_live_qdrant_and_ollama_hosts_respond():
    import requests

    qdrant = os.environ.get("QDRANT_HOST", "http://localhost:6333").rstrip("/")
    ollama = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    qdrant_response = requests.get(f"{qdrant}/collections", timeout=5)
    ollama_response = requests.get(f"{ollama}/api/tags", timeout=5)

    assert qdrant_response.status_code == 200
    assert ollama_response.status_code == 200
