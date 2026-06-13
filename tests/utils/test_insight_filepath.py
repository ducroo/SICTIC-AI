from lib.insight_filepath import get_insight_filepath
from lib.storage import get_storage
from lib.storage_domains import dataset_location_for_domain


def _create_dataset(name: str, domain: str):
    get_storage().mkdir(
        dataset_location_for_domain(name, domain).raw_rel
    )


def test_insight_filepath_root(mock_env):
    _create_dataset("daav", "startups")
    path = get_insight_filepath(
        dataset_name="daav",
        skill_name="startup_profile",
        model="ollama/gemma4:31b-nvfp4",
        subdir=False
    )
    assert path == "storage/startups/daav/insights/startup-profile-daav-gemma4-31b-nvfp4.md"

def test_insight_filepath_subdir(mock_env):
    path = get_insight_filepath(
        dataset_name="sictic-members",
        skill_name="person_profile",
        model="ollama/gemma4:31b-nvfp4",
        identifier="Urs Gubser",
        subdir=True
    )
    assert path == "storage/community/sictic-members/insights/person-profile/urs-gubser-gemma4-31b-nvfp4.md"

def test_insight_filepath_batch_audit(mock_env):
    _create_dataset("daav", "startups")
    path = get_insight_filepath(
        dataset_name="daav",
        skill_name="batch_audit",
        model="gemma4:31b-nvfp4",
        identifier="1. Elevator",
        subdir=True
    )
    assert path == "storage/startups/daav/insights/batch-audit/1-elevator-gemma4-31b-nvfp4.md"
