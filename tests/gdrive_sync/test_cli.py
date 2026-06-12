from types import SimpleNamespace

import pytest

from skills.gdrive_sync import cli


def test_sync_requires_explicit_conflict_winner():
    with pytest.raises(SystemExit) as exc:
        cli.main(["sync"])

    assert exc.value.code == 2


def test_conflict_winner_flags_only_apply_to_sync():
    with pytest.raises(SystemExit) as exc:
        cli.main(["pull", "--local-wins"])

    assert exc.value.code == 2


def test_legacy_conflict_policy_flag_is_rejected():
    with pytest.raises(SystemExit) as exc:
        cli.main(["sync", "--conflict-policy", "local-wins"])

    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("flag", "expected_policy"),
    [
        ("--local-wins", "local-wins"),
        ("--cloud-wins", "cloud-wins"),
    ],
)
def test_sync_winner_flag_maps_to_internal_policy(monkeypatch, flag, expected_policy):
    calls = {}

    class FakeSync:
        def __init__(self, **_kwargs):
            pass

        def sync(self, *, conflict_policy, dry_run):
            calls["conflict_policy"] = conflict_policy
            calls["dry_run"] = dry_run
            return SimpleNamespace(
                operation="sync",
                created_files=[],
                updated_files=[],
                deleted_entries=[],
                conflicts=[],
                warnings=[],
                bytes_transferred=0,
                elapsed_seconds=0.0,
            )

    monkeypatch.setattr(cli, "GDriveSync", FakeSync)

    assert cli.main(["sync", flag, "--dry-run"]) == 0
    assert calls == {
        "conflict_policy": expected_policy,
        "dry_run": True,
    }
