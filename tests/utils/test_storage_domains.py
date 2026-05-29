from lib.storage_domains import (
    dataset_insights_path,
    dataset_parsed_path,
    dataset_raw_path,
    persons_registry_path,
)


def test_startup_dataset_paths_use_startup_domain():
    assert dataset_raw_path("Avientus") == "datasets/startups/avientus"
    assert dataset_parsed_path("Avientus") == "cache/datasets2md/startups/avientus"
    assert dataset_insights_path("Avientus") == "insights/startups/avientus"


def test_community_dataset_paths_use_configured_domain():
    assert dataset_raw_path("sictic_members") == "datasets/community/sictic-members"
    assert dataset_parsed_path("sictic_members") == "cache/datasets2md/community/sictic-members"
    assert dataset_insights_path("sictic_members") == "insights/community/sictic-members"
    assert persons_registry_path("sictic_members") == "registry/persons/sictic-members.md"


def test_derived_dataset_paths_use_derived_domain():
    assert dataset_raw_path("person_profile") == "derived/person-profile"
    assert dataset_parsed_path("person_profile") == "cache/datasets2md/derived/person-profile"
