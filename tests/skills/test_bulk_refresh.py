import pytest

from lib.storage import get_storage
from lib.storage_domains import dataset_location_for_domain
from skills.bulk_refresh import bulk_refresh as bulk_refresh_module
from skills.skill_registry import (
    SKILL_REGISTRY,
    SkillSpec,
    expand_skill_dependencies,
)


def test_person_profile_dependency_includes_persons_in_dataset():
    assert expand_skill_dependencies(["person-profile"]) == [
        "persons-in-dataset",
        "person-profile",
    ]


def test_persons_in_dataset_can_be_selected_directly():
    assert expand_skill_dependencies(["persons-in-dataset"]) == [
        "persons-in-dataset"
    ]


def test_nested_dependencies_are_expanded_in_registry_order():
    assert expand_skill_dependencies(["investor-profile"]) == [
        "persons-in-dataset",
        "person-profile",
        "investor-profile",
    ]


@pytest.mark.parametrize(
    "skill_name",
    ["expert-search", "potential-investors", "suggested-startups"],
)
def test_member_matching_skills_depend_on_investor_profile(skill_name):
    dependencies = expand_skill_dependencies([skill_name])

    assert "persons-in-dataset" in dependencies
    assert "person-profile" in dependencies
    assert "investor-profile" in dependencies


def test_registry_declares_domain_applicability():
    assert SKILL_REGISTRY["startup-profile"].domains == frozenset({"startups"})
    assert SKILL_REGISTRY["person-profile"].domains == frozenset(
        {"startups", "community"}
    )
    assert all(
        "generated" not in skill.domains
        for skill in SKILL_REGISTRY.values()
    )


@pytest.mark.asyncio
async def test_person_profile_runs_persons_dependency_first(mock_env, mocker):
    calls = []

    async def fake_sync(datasets):
        calls.append(("sync", tuple(datasets)))

    async def fake_persons(dataset_name):
        calls.append(("persons-in-dataset", dataset_name))

    async def fake_profile(dataset_name):
        calls.append(("person-profile", dataset_name))

    location = dataset_location_for_domain("sictic-members", "community")
    get_storage().mkdir(location.raw_rel)
    mocker.patch.object(bulk_refresh_module, "sync_datasets", side_effect=fake_sync)
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "persons-in-dataset": SkillSpec(
                func=fake_persons,
                domains=frozenset({"startups", "community"}),
            ),
            "person-profile": SkillSpec(
                func=fake_profile,
                domains=frozenset({"startups", "community"}),
                depends_on=("persons-in-dataset",),
            ),
        },
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
async def test_generated_dataset_is_ingested_but_has_no_applicable_skills(
    mock_env,
    mocker,
):
    location = dataset_location_for_domain(
        "sictic-members-person-profile",
        "generated",
    )
    get_storage().mkdir(location.raw_rel)
    sync = mocker.patch.object(bulk_refresh_module, "sync_datasets")
    persons = mocker.AsyncMock()
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "persons-in-dataset": SkillSpec(
                func=persons,
                domains=frozenset({"startups", "community"}),
            )
        },
    )

    await bulk_refresh_module.bulk_refresh(
        target_dataset="sictic-members-person-profile",
        target_skill="persons-in-dataset",
    )

    sync.assert_awaited_once_with(["sictic-members-person-profile"])
    persons.assert_not_called()
