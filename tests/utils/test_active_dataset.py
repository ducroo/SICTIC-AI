import time

from lib.active_dataset import (
    MARKER_TEXT,
    activate_dataset,
    archive_dataset,
    dataset_archived_marker_path,
    is_active_dataset,
)
from lib.storage import get_storage
from lib.storage_domains import (
    dataset_active_marker_path,
    dataset_location_for_domain,
)


def _create_startup_dataset():
    get_storage().mkdir(
        dataset_location_for_domain("Avientus", "startups").raw_rel
    )


def test_activate_dataset_writes_current_active_marker(mock_env):
    _create_startup_dataset()
    started_at = time.time()
    activate_dataset("Avientus")

    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    archived_marker = dataset_archived_marker_path("Avientus")

    assert storage.exists(active_marker)
    assert not storage.exists(archived_marker)
    assert storage.read_text(active_marker) == MARKER_TEXT
    assert storage.mtime(active_marker) >= started_at
    assert is_active_dataset("Avientus")


def test_archive_dataset_replaces_active_marker_with_archived_marker(mock_env):
    _create_startup_dataset()
    activate_dataset("Avientus")
    archive_dataset("Avientus")

    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    archived_marker = dataset_archived_marker_path("Avientus")

    assert not storage.exists(active_marker)
    assert storage.exists(archived_marker)
    assert storage.read_text(archived_marker) == MARKER_TEXT
    assert not is_active_dataset("Avientus")


def test_activate_dataset_replaces_archived_marker_with_active_marker(mock_env):
    _create_startup_dataset()
    archive_dataset("Avientus")
    activate_dataset("Avientus")

    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    archived_marker = dataset_archived_marker_path("Avientus")

    assert storage.exists(active_marker)
    assert not storage.exists(archived_marker)
    assert storage.read_text(active_marker) == MARKER_TEXT


def test_archive_dataset_by_age_writes_archived_marker(mock_env):
    _create_startup_dataset()
    activate_dataset("Avientus")
    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    old_mtime = time.time() - (2 * 86400)
    storage.set_mtime(active_marker, old_mtime)

    archive_dataset(age_days=1)

    assert not storage.exists(active_marker)
    assert storage.exists(dataset_archived_marker_path("Avientus"))


def test_activate_dataset_does_not_touch_existing_marker(mock_env):
    _create_startup_dataset()
    activate_dataset("Avientus")
    storage = get_storage()
    marker = dataset_active_marker_path("Avientus")
    original_mtime = 1_700_000_000.0
    storage.set_mtime(marker, original_mtime)

    activate_dataset("Avientus")

    assert storage.mtime(marker) == original_mtime
