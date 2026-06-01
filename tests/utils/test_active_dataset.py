from lib.active_dataset import (
    MARKER_MTIME,
    MARKER_TEXT,
    activate_dataset,
    archive_dataset,
    dataset_archived_marker_path,
    is_active_dataset,
)
from lib.storage import get_storage, reset_storage_singleton
from lib.storage_domains import dataset_active_marker_path


def test_activate_dataset_writes_active_marker_and_backdates_it(mock_env):
    activate_dataset("Avientus")

    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    archived_marker = dataset_archived_marker_path("Avientus")

    assert storage.exists(active_marker)
    assert not storage.exists(archived_marker)
    assert storage.read_text(active_marker) == MARKER_TEXT
    assert storage.mtime(active_marker) == MARKER_MTIME
    assert is_active_dataset("Avientus")


def test_archive_dataset_replaces_active_marker_with_archived_marker(mock_env):
    activate_dataset("Avientus")
    archive_dataset("Avientus")

    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    archived_marker = dataset_archived_marker_path("Avientus")

    assert not storage.exists(active_marker)
    assert storage.exists(archived_marker)
    assert storage.read_text(archived_marker) == MARKER_TEXT
    assert storage.mtime(archived_marker) == MARKER_MTIME
    assert not is_active_dataset("Avientus")


def test_activate_dataset_replaces_archived_marker_with_active_marker(mock_env):
    archive_dataset("Avientus")
    activate_dataset("Avientus")

    storage = get_storage()
    active_marker = dataset_active_marker_path("Avientus")
    archived_marker = dataset_archived_marker_path("Avientus")

    assert storage.exists(active_marker)
    assert not storage.exists(archived_marker)
    assert storage.read_text(active_marker) == MARKER_TEXT
    assert storage.mtime(active_marker) == MARKER_MTIME


def test_archive_dataset_by_age_writes_archived_marker(mock_env):
    activate_dataset("Avientus")
    archive_dataset(age_days=1)

    storage = get_storage()
    assert not storage.exists(dataset_active_marker_path("Avientus"))
    assert storage.exists(dataset_archived_marker_path("Avientus"))


def test_marker_mtime_is_31_dec_1999_gmt(mock_env):
    activate_dataset("Avientus")
    reset_storage_singleton()

    storage = get_storage()
    assert storage.mtime(dataset_active_marker_path("Avientus")) == 946598400.0
