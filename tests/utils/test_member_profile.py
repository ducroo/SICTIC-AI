import pytest


@pytest.mark.asyncio
async def test_member_profile_hydrates_from_insights_instead_of_writing_derived_files(mocker):
    from lib.models.person import Person
    import lib.member_profile as member_profile_module

    mock_person_profile = mocker.patch.object(
        member_profile_module,
        "person_profile",
        return_value=[Person(full_name="Urs Gubser", person_profile="profile text")],
    )
    mock_hydrate = mocker.patch.object(member_profile_module, "dataset_from_insight")

    result = await member_profile_module.member_profile("person_profile", "Urs Gubser")

    assert result == "profile text"
    mock_person_profile.assert_called_once_with(dataset_name="sictic_members", names="Urs Gubser")
    mock_hydrate.assert_called_once_with(
        insight_name="person_profile",
        source_dataset="sictic-members",
    )
