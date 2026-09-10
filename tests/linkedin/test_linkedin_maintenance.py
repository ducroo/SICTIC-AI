import json

from typer.testing import CliRunner

from lib.people.linkedin.registry import LinkedInRegistry
from lib.storage import get_storage
from skills.linkedin_maintenance import __main__ as linkedin_cli
from skills.linkedin_maintenance.maintenance import import_profiles


def test_import_uses_linkedin_id_for_cache_filename_not_registry_key(
    mock_env,
    tmp_path,
):
    registry = LinkedInRegistry(tmp_path / "linkedin-registry.json")
    registry.save(
        {
            "Patrick Schuler": {
                "datasets": ["sictic-members"],
                "full_name": "Patrick Schuler",
                "linkedin_id": "schulerp",
                "status": "open",
            }
        }
    )
    import_file = tmp_path / "profiles.json"
    import_file.write_text(
        json.dumps(
            {
                "publicIdentifier": "schulerp",
                "fullName": "Patrick Schuler",
            }
        ),
        encoding="utf-8",
    )

    count = import_profiles(
        str(import_file),
        registry=registry,
        storage=get_storage(),
    )

    assert count == 1
    assert get_storage().exists(
        "storage/community/sictic-members/datasets/linkedin/schulerp.json"
    )
    assert not get_storage().exists(
        "storage/community/sictic-members/datasets/linkedin/Patrick Schuler.json"
    )
    assert registry.load() == {}


def test_missing_cli_outputs_plain_linkedin_urls(monkeypatch):
    monkeypatch.setattr(
        linkedin_cli,
        "missing_profiles",
        lambda: [
            {
                "registry_key": "schulerp",
                "linkedin_id": "schulerp",
                "status": "open",
            },
            {
                "registry_key": "email:missing@example.com",
                "linkedin_id": "",
                "status": "not_found",
            },
            {
                "registry_key": "ralph-mogicato",
                "linkedin_id": "ralph-mogicato",
                "status": "failed",
            },
        ],
    )

    result = CliRunner().invoke(linkedin_cli.app, ["missing"])

    assert result.exit_code == 0
    assert result.output == (
        "https://www.linkedin.com/in/ralph-mogicato/\n"
        "https://www.linkedin.com/in/schulerp/\n"
    )


def test_generic_import_error_remains_actionable(mock_env, tmp_path):
    registry = LinkedInRegistry(tmp_path / "linkedin-registry.json")
    registry.upsert(
        "jane-doe",
        dataset="sictic-members",
        full_name="Jane Doe",
        linkedin_id="jane-doe",
        status="open",
    )
    import_file = tmp_path / "profiles.json"
    import_file.write_text(
        json.dumps(
            {
                "publicIdentifier": "jane-doe",
                "error": "subscription required",
            }
        ),
        encoding="utf-8",
    )

    assert import_profiles(str(import_file), registry=registry) == 0
    assert registry.load()["jane-doe"]["status"] == "failed"
