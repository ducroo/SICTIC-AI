import pytest

from skills.bulk_refresh import bulk_refresh as bulk_refresh_module


def test_person_profile_dependency_includes_persons_in_dataset():
    assert bulk_refresh_module._expand_skill_dependencies(["person-profile"]) == [
        "persons-in-dataset",
        "person-profile",
    ]


def test_persons_in_dataset_can_be_selected_directly():
    assert bulk_refresh_module._expand_skill_dependencies(
        ["persons-in-dataset"]
    ) == ["persons-in-dataset"]


def test_nested_dependencies_are_expanded_in_registry_order():
    assert bulk_refresh_module._expand_skill_dependencies(["investor-profile"]) == [
        "persons-in-dataset",
        "person-profile",
        "investor-profile",
    ]


@pytest.mark.parametrize(
    "skill_name",
    ["expert-search", "potential-investors", "suggested-startups"],
)
def test_member_matching_skills_depend_on_investor_profile(skill_name):
    dependencies = bulk_refresh_module._expand_skill_dependencies([skill_name])

    assert "persons-in-dataset" in dependencies
    assert "person-profile" in dependencies
    assert "investor-profile" in dependencies


@pytest.mark.parametrize(
    "dataset_name",
    [
        "person-profile",
        "active-person-profile",
        "sictic-members-person-profile",
        "avientus-startup-profile",
        "active-investor-profile",
    ],
)
def test_insight_derived_dataset_names_are_detected(dataset_name):
    assert bulk_refresh_module._is_insight_derived_dataset(dataset_name)


def test_normal_dataset_names_are_not_treated_as_derived():
    assert not bulk_refresh_module._is_insight_derived_dataset("avientus")
    assert not bulk_refresh_module._is_insight_derived_dataset("sictic-members")


@pytest.mark.asyncio
async def test_person_profile_runs_persons_dependency_first(mocker):
    calls = []

    async def fake_sync(datasets):
        calls.append(("sync", tuple(datasets)))

    async def fake_persons(dataset_name):
        calls.append(("persons-in-dataset", dataset_name))

    async def fake_profile(dataset_name):
        calls.append(("person-profile", dataset_name))

    mocker.patch.object(bulk_refresh_module, "sync_datasets", side_effect=fake_sync)
    mocker.patch.dict(
        bulk_refresh_module.SKILL_MAP["persons-in-dataset"],
        {"func": fake_persons},
    )
    mocker.patch.dict(
        bulk_refresh_module.SKILL_MAP["person-profile"],
        {"func": fake_profile},
    )

    await bulk_refresh_module.bulk_refresh(
        target_dataset="sictic-members",
        target_skill="person-profile",
    )

    assert calls == [
        ("sync", ("sictic-members",)),
        ("persons-in-dataset", "sictic-members"),
        ("person-profile", "sictic-members"),
    ]


@pytest.mark.asyncio
async def test_explicit_insight_derived_dataset_is_skipped(mocker):
    sync = mocker.patch.object(bulk_refresh_module, "sync_datasets")
    persons = mocker.patch.object(
        bulk_refresh_module,
        "_refresh_persons_in_dataset",
    )

    await bulk_refresh_module.bulk_refresh(
        target_dataset="sictic-members-person-profile",
        target_skill="persons-in-dataset",
    )

    sync.assert_not_called()
    persons.assert_not_called()
