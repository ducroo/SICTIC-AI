from lib.insight_filepath import get_insight_filepath

def test_insight_filepath_root():
    path = get_insight_filepath(
        dataset_name="daav",
        skill_name="startup_profile",
        model="ollama/gemma4:31b-nvfp4",
        subdir=False
    )
    assert path == "insights/daav/startup-profile-daav-gemma4-31b-nvfp4.md"

def test_insight_filepath_subdir():
    path = get_insight_filepath(
        dataset_name="community",
        skill_name="person_profile",
        model="ollama/gemma4:31b-nvfp4",
        identifier="Urs Gubser",
        subdir=True
    )
    assert path == "insights/community/person-profile/urs-gubser-gemma4-31b-nvfp4.md"

def test_insight_filepath_batch_audit():
    path = get_insight_filepath(
        dataset_name="daav",
        skill_name="batch_audit",
        model="gemma4:31b-nvfp4",
        identifier="1. Elevator",
        subdir=True
    )
    assert path == "insights/daav/batch-audit/1-elevator-gemma4-31b-nvfp4.md"
