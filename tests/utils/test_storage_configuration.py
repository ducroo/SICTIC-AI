from lib import storage as storage_module
from lib.storage import LocalStorage


def test_local_storage_provider_uses_local_storage_path(monkeypatch, tmp_path):
    local_root = tmp_path / "application-storage"
    monkeypatch.setenv("STORAGE_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(local_root))
    monkeypatch.setenv("CLOUD_PROVIDER", "google")
    monkeypatch.setenv("CLOUD_STORAGE_PATH", "unused-cloud-root")
    storage_module.reset_storage_singleton()

    storage = storage_module.get_storage()

    assert isinstance(storage, LocalStorage)
    assert storage.base == local_root
