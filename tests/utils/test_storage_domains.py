import pytest

from lib.storage import get_storage
from lib.storage_domains import (
    dataset_insights_path,
    dataset_location,
    dataset_location_for_domain,
    dataset_parsed_path,
    dataset_raw_path,
)


def _create_dataset(name: str, domain: str):
    location = dataset_location_for_domain(name, domain)
    get_storage().mkdir(location.raw_rel)
    return location


def test_startup_dataset_is_discovered_by_name(mock_env):
    _create_dataset("Avientus", "startups")

    assert dataset_location("Avientus").domain == "startups"
    assert dataset_raw_path("Avientus") == "storage/startups/avientus/datasets"
    assert dataset_parsed_path("Avientus") == "docling_data/datasets2md/startups/avientus/datasets"
    assert dataset_insights_path("Avientus") == "storage/startups/avientus/insights"


def test_community_dataset_is_discovered_by_name(mock_env):
    _create_dataset("sictic_members", "community")

    assert dataset_location("sictic_members").domain == "community"
    assert dataset_raw_path("sictic_members") == "storage/community/sictic-members/datasets"
    assert dataset_parsed_path("sictic_members") == (
        "docling_data/datasets2md/community/sictic-members/datasets"
    )
    assert dataset_insights_path("sictic_members") == "storage/community/sictic-members/insights"


def test_generated_dataset_is_discovered_by_name(mock_env):
    _create_dataset("sictic-members-investor-profile", "generated")

    assert dataset_location("sictic-members-investor-profile").domain == "generated"
    assert dataset_raw_path("sictic-members-investor-profile") == (
        "storage/generated/sictic-members-investor-profile/datasets"
    )
    assert dataset_parsed_path("sictic-members-investor-profile") == (
        "docling_data/datasets2md/generated/sictic-members-investor-profile/datasets"
    )


def test_missing_dataset_is_rejected(mock_env):
    with pytest.raises(FileNotFoundError, match="missing"):
        dataset_location("missing")


def test_duplicate_dataset_name_is_rejected(mock_env):
    _create_dataset("duplicate", "startups")
    _create_dataset("duplicate", "community")

    with pytest.raises(ValueError, match="multiple domains"):
        dataset_location("duplicate")
