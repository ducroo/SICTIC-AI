import json

from lib.linkedin.registry import LinkedInRegistry
from lib.storage import get_storage
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
