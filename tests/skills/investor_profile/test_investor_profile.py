from unittest.mock import patch

import pytest

from lib.people.model import Person
from lib.storage import get_storage
from skills.investor_profile.investor_profile import investor_profile


@pytest.mark.asyncio
async def test_investor_profile_builds_every_model_variant(mock_env):
    storage = get_storage()
    person_dir = "storage/community/sictic-members/insights/person-profile"
    track_record_dir = "storage/community/sictic-members/datasets/track-record"
    output_dir = "storage/community/sictic-members/insights/investor-profile"

    storage.write_text(
        f"{person_dir}/urs-gubser-gemma4-31b-nvfp4.md",
        "# Person Profile\n\nGemma profile.",
    )
    storage.write_text(
        f"{person_dir}/urs-gubser-qwen3-8b.md",
        "# Person Profile\n\nQwen profile.",
    )
    storage.write_text(
        f"{track_record_dir}/urs-gubser.md",
        "# Track Record\n\nInvested in Example AG.",
    )
    storage.write_text(
        f"{person_dir}/not-a-member-gemma4-31b-nvfp4.md",
        "# Person Profile\n\nNot a member.",
    )

    with patch(
        "lib.people.discovery.persons_in_dataset",
        return_value=[Person(linkedin_id="urs-gubser")],
    ):
        result = await investor_profile()

    assert len(result) == 2
    assert all(insight.exists() for insight in result)
    assert storage.read_text(
        f"{output_dir}/urs-gubser-gemma4-31b-nvfp4.md"
    ) == (
        "# Person Profile\n\nGemma profile.\n\n"
        "## Investment Track Record and Preferences\n\n"
        "# Track Record\n\nInvested in Example AG.\n"
    )
    assert storage.read_text(
        f"{output_dir}/urs-gubser-qwen3-8b.md"
    ).startswith("# Person Profile\n\nQwen profile.")
    assert not storage.exists(
        f"{output_dir}/not-a-member-gemma4-31b-nvfp4.md"
    )


@pytest.mark.asyncio
async def test_investor_profile_adds_note_when_track_record_is_missing(mock_env):
    storage = get_storage()
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/jane-doe-gemma4-31b-nvfp4.md",
        "# Person Profile\n\nJane profile.",
    )

    with patch(
        "lib.people.discovery.persons_in_dataset",
        return_value=[Person(linkedin_id="jane-doe")],
    ):
        result = await investor_profile()

    output = storage.read_text(
        "storage/community/sictic-members/insights/investor-profile/jane-doe-gemma4-31b-nvfp4.md"
    )
    assert len(result) == 1
    assert output.endswith(
        "## Investment Track Record and Preferences\n\n"
        "No investment track record available, likely has not invested before.\n"
    )


@pytest.mark.asyncio
async def test_investor_profile_skips_filename_without_model(mock_env):
    storage = get_storage()
    storage.write_text(
        "storage/community/sictic-members/insights/person-profile/not-a-profile.md",
        "Invalid source.",
    )

    with patch(
        "lib.people.discovery.persons_in_dataset",
        return_value=[],
    ):
        result = await investor_profile()

    assert result == []
