from pathlib import Path

import pytest

from gdrive_sync import client
from gdrive_sync.logging_config import default_log_dir
from gdrive_sync.state import default_state_dir


class _FakeDriveTree:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_gdrive_sync_requires_google_cloud_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUD_PROVIDER", "dropbox")

    with pytest.raises(ValueError, match="CLOUD_PROVIDER=google"):
        client.GDriveSync(
            local_root=str(tmp_path / "local"),
            gdrive_root="cloud-root",
            state_dir=str(tmp_path / "state"),
            log_dir=str(tmp_path / "logs"),
        )


def test_gdrive_sync_uses_new_environment_roots(monkeypatch, tmp_path):
    local_root = tmp_path / "local"
    monkeypatch.setenv("CLOUD_PROVIDER", "GoOgLe")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(local_root))
    monkeypatch.setenv("CLOUD_STORAGE_PATH", "cloud-root")
    monkeypatch.setattr(client, "DriveTree", _FakeDriveTree)

    syncer = client.GDriveSync(
        state_dir=str(tmp_path / "state"),
        log_dir=str(tmp_path / "logs"),
    )

    assert syncer.local_root == str(local_root)
    assert syncer.gdrive_root == "cloud-root"
    assert syncer.local.root == Path(local_root)
    assert syncer.drive.kwargs["root_folder_id"] == "cloud-root"


def test_gdrive_sync_requires_explicit_cloud_root(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUD_PROVIDER", "google")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "local"))
    monkeypatch.delenv("CLOUD_STORAGE_PATH", raising=False)

    with pytest.raises(ValueError, match="CLOUD_STORAGE_PATH must be set explicitly"):
        client.GDriveSync(
            state_dir=str(tmp_path / "state"),
            log_dir=str(tmp_path / "logs"),
        )


def test_gdrive_sync_allows_explicit_drive_root(monkeypatch, tmp_path):
    local_root = tmp_path / "local"
    monkeypatch.setenv("CLOUD_PROVIDER", "google")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(local_root))
    monkeypatch.setenv("CLOUD_STORAGE_PATH", "root")
    monkeypatch.setattr(client, "DriveTree", _FakeDriveTree)

    syncer = client.GDriveSync(
        state_dir=str(tmp_path / "state"),
        log_dir=str(tmp_path / "logs"),
    )

    assert syncer.gdrive_root == "root"
    assert syncer.drive.kwargs["root_folder_id"] == "root"


def test_default_operational_paths_use_repo_path(monkeypatch, tmp_path):
    monkeypatch.setenv("REPO_PATH", str(tmp_path))

    assert default_state_dir() == tmp_path / "gdrive_sync_state"
    assert default_log_dir() == tmp_path / "logs"
