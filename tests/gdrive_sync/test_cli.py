from types import SimpleNamespace

from gdrive_sync import cli


def _result(operation: str) -> SimpleNamespace:
    return SimpleNamespace(
        operation=operation,
        dry_run=True,
        created_files=[],
        created_folders=[],
        updated_files=[],
        deleted_entries=[],
        conflicts=[],
        skipped_entries=[],
        warnings=[],
        failures=[],
        bytes_transferred=0,
        elapsed_seconds=0.0,
    )


def test_sync_conflict_policy_maps_to_client(monkeypatch):
    calls = {}

    class FakeSync:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def sync(self, *, conflict_policy, dry_run):
            calls["conflict_policy"] = conflict_policy
            calls["dry_run"] = dry_run
            return _result("sync")

    monkeypatch.setattr(cli, "GDriveSync", FakeSync)

    assert cli.main(["sync", "--cloud-root", "drive", "--conflict-policy", "cloud-wins", "--dry-run"]) == 0
    assert calls["init"]["gdrive_root"] == "drive"
    assert calls["conflict_policy"] == "cloud-wins"
    assert calls["dry_run"] is True


def test_pull_maps_to_client(monkeypatch):
    calls = {}

    class FakeSync:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def pull(self, *, dry_run):
            calls["dry_run"] = dry_run
            return _result("pull")

    monkeypatch.setattr(cli, "GDriveSync", FakeSync)

    assert cli.main(["pull", "--local-root", "/tmp/local", "--dry-run"]) == 0
    assert calls["init"]["local_root"] == "/tmp/local"
    assert calls["dry_run"] is True


def test_push_maps_to_client(monkeypatch):
    calls = {}

    class FakeSync:
        def __init__(self, **kwargs):
            calls["init"] = kwargs

        def push(self, *, dry_run):
            calls["dry_run"] = dry_run
            return _result("push")

    monkeypatch.setattr(cli, "GDriveSync", FakeSync)

    assert cli.main(["push", "--dry-run"]) == 0
    assert calls["dry_run"] is True
