from lib import storage as storage_module
from lib.storage import LocalStorage, RoutedStorage


def test_storage_uses_local_storage_paths(monkeypatch, tmp_path):
    local_root = tmp_path / "application-storage"
    local_data_root = tmp_path / "local-data"
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(local_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(local_data_root))
    monkeypatch.setenv("CLOUD_PROVIDER", "google")
    monkeypatch.setenv("CLOUD_STORAGE_PATH", "unused-cloud-root")
    storage_module.reset_storage_singleton()

    storage = storage_module.get_storage()

    assert isinstance(storage, RoutedStorage)
    assert isinstance(storage.primary, LocalStorage)
    assert isinstance(storage.cache, LocalStorage)
    assert storage.primary.base == local_root
    assert storage.cache.base == local_data_root

    storage.write_text("storage/startups/example/insights/report.md", "# Report\n")
    storage.write_text("docling_data/datasets2md/startups/example/deck.pdf.md", "# Parsed\n")

    assert (local_root / "storage/startups/example/insights/report.md").exists()
    assert not (local_root / "docling_data").exists()
    assert (
        local_data_root / "docling_data/datasets2md/startups/example/deck.pdf.md"
    ).exists()


def test_legacy_storage_provider_cannot_enable_drive_access(monkeypatch, tmp_path):
    local_root = tmp_path / "application-storage"
    monkeypatch.setenv("STORAGE_PROVIDER", "google")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(local_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path / "local-data"))
    storage_module.reset_storage_singleton()

    storage = storage_module.get_storage()
    storage.write_text("storage/probe.md", "local")

    assert (local_root / "storage/probe.md").read_text() == "local"
