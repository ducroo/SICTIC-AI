from lib.storage_domains import (
    dataset_insights_path,
    dataset_parsed_path,
    dataset_raw_path,
)


def test_startup_dataset_paths_use_startup_domain():
    assert dataset_raw_path("Avientus") == "storage/startups/avientus/datasets"
    assert dataset_parsed_path("Avientus") == "storage/datasets2md/startups/avientus/datasets"
    assert dataset_insights_path("Avientus") == "storage/startups/avientus/insights"


def test_community_dataset_paths_use_configured_domain():
    assert dataset_raw_path("sictic_members") == "storage/community/sictic-members/datasets"
    assert dataset_parsed_path("sictic_members") == "storage/datasets2md/community/sictic-members/datasets"
    assert dataset_insights_path("sictic_members") == "storage/community/sictic-members/insights"


def test_derived_dataset_paths_use_derived_domain():
    assert dataset_raw_path("person_profile") == "storage/community/person-profile/datasets"
    assert dataset_parsed_path("person_profile") == "storage/datasets2md/community/person-profile/datasets"
