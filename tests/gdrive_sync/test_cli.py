from types import SimpleNamespace

from typer.testing import CliRunner

from skills.gdrive_sync import __main__ as cli


runner = CliRunner()


def test_sync_requires_explicit_conflict_winner():
    result = runner.invoke(cli.app, ["sync"])

    assert result.exit_code == 2
    assert "choose exactly one" in result.output


def test_sync_rejects_two_conflict_winners():
    result = runner.invoke(cli.app, ["sync", "--local-wins", "--cloud-wins"])

    assert result.exit_code == 2
    assert "choose exactly one" in result.output


def test_conflict_winner_flags_only_apply_to_sync():
    result = runner.invoke(cli.app, ["pull", "--local-wins"])

    assert result.exit_code == 2


def test_push_command_is_not_supported():
    result = runner.invoke(cli.app, ["push"])

    assert result.exit_code == 2


def test_legacy_conflict_policy_flag_is_rejected():
    result = runner.invoke(
        cli.app,
        ["sync", "--conflict-policy", "local-wins"],
    )

    assert result.exit_code == 2


def test_sync_winner_flag_maps_to_internal_policy(monkeypatch):
    calls = {}

    def fake_run(operation, **kwargs):
        calls["operation"] = operation
        calls.update(kwargs)
        return SimpleNamespace(
            operation="sync",
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

    monkeypatch.setattr(cli, "run_operation", fake_run)

    result = runner.invoke(cli.app, ["sync", "--cloud-wins", "--dry-run"])

    assert result.exit_code == 0
    assert calls["operation"] == "sync"
    assert calls["conflict_policy"] == "cloud-wins"
    assert calls["dry_run"] is True
