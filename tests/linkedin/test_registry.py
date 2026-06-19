import json

from lib.linkedin.registry import LinkedInRegistry


def test_registry_migrates_single_dataset_and_adds_associations(tmp_path):
    path = tmp_path / "linkedin-registry.json"
    path.write_text(
        json.dumps(
            {
                "schulerp": {
                    "dataset": "sictic-members",
                    "full_name": "Patrick Schuler",
                    "linkedin_id": "schulerp",
                    "status": "PENDING",
                }
            }
        ),
        encoding="utf-8",
    )
    registry = LinkedInRegistry(path)

    registry.upsert(
        "schulerp",
        dataset="another-dataset",
        full_name="Patrick Schuler",
        linkedin_id="schulerp",
        status="PENDING",
    )

    assert registry.load()["schulerp"]["datasets"] == [
        "another-dataset",
        "sictic-members",
    ]
    assert "dataset" not in registry.load()["schulerp"]


def test_registry_can_find_identity_stored_under_legacy_name_key(tmp_path):
    registry = LinkedInRegistry(tmp_path / "linkedin-registry.json")
    registry.save(
        {
            "Patrick Schuler": {
                "datasets": ["sictic-members"],
                "linkedin_id": "schulerp",
                "status": "PENDING",
            }
        }
    )

    key, entry = registry.find("schulerp", "schulerp")

    assert key == "Patrick Schuler"
    assert entry["linkedin_id"] == "schulerp"
