import json

from typer.testing import CliRunner

from lib.linkedin.registry import LinkedInRegistry
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
                "status": "PENDING",
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
                "status": "PENDING",
            },
            {
                "registry_key": "email:missing@example.com",
                "linkedin_id": "",
                "status": "URL_NOT_FOUND",
            },
            {
                "registry_key": "ralph-mogicato",
                "linkedin_id": "ralph-mogicato",
                "status": "SCRAPE_FAILED",
            },
        ],
    )

    result = CliRunner().invoke(linkedin_cli.app, ["missing"])

    assert result.exit_code == 0
    assert result.output == (
        "https://www.linkedin.com/in/ralph-mogicato/\n"
        "https://www.linkedin.com/in/schulerp/\n"
    )
