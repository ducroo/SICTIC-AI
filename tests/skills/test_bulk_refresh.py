import asyncio
from types import SimpleNamespace

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from skills.bulk_refresh import bulk_refresh as bulk_refresh_module
from skills.skill_registry import SkillSpec, expand_skill_dependencies


def test_person_profile_dependency_includes_persons_in_dataset():
    assert expand_skill_dependencies(["person-profile"]) == [
        "persons-in-dataset",
        "person-profile",
    ]


def test_nested_dependencies_are_expanded_in_registry_order():
    assert expand_skill_dependencies(["investor-profile"]) == [
        "persons-in-dataset",
        "person-profile",
        "investor-profile",
    ]


def test_default_dataset_scope_is_active_source_domains(mocker):
    locations = {
        "active-startup": SimpleNamespace(domain="startups"),
        "inactive-member": SimpleNamespace(domain="community"),
    }
    list_names = mocker.patch.object(
        bulk_refresh_module,
        "list_all_dataset_names",
        return_value=list(locations),
    )
    mocker.patch.object(
        bulk_refresh_module,
        "dataset_location",
        side_effect=lambda name: locations[name],
    )
    mocker.patch.object(
        bulk_refresh_module,
        "is_active_dataset",
        side_effect=lambda name: name == "active-startup",
    )

    scope = bulk_refresh_module._select_datasets(None)

    assert scope.names == ("active-startup",)
    list_names.assert_called_once_with(domains=("startups", "community"))


def test_all_dataset_scope_includes_inactive_source_datasets(mocker):
    locations = {
        "active-startup": SimpleNamespace(domain="startups"),
        "inactive-member": SimpleNamespace(domain="community"),
    }
    mocker.patch.object(
        bulk_refresh_module,
        "list_all_dataset_names",
        return_value=list(locations),
    )
    mocker.patch.object(
        bulk_refresh_module,
        "dataset_location",
        side_effect=lambda name: locations[name],
    )

    scope = bulk_refresh_module._select_datasets("all")

    assert scope.names == ("active-startup", "inactive-member")


def test_explicit_generated_dataset_is_rejected(mock_env):
    location = dataset_location_for_domain("person-profile", "generated")
    get_storage().mkdir(location.raw_rel)

    with pytest.raises(ValueError, match="unsupported bulk-refresh domain"):
        bulk_refresh_module._select_datasets("person-profile")


@pytest.mark.asyncio
async def test_dependencies_run_before_dependants(mock_env, mocker):
    calls = []

    async def fake_sync(datasets, raise_on_error=False):
        calls.append(("sync", tuple(datasets), raise_on_error))

    async def fake_persons(dataset):
        calls.append(("persons-in-dataset", dataset))

    async def fake_profile(dataset):
        calls.append(("person-profile", dataset))

    location = dataset_location_for_domain("sictic-members", "community")
    get_storage().mkdir(location.raw_rel)
    mocker.patch.object(bulk_refresh_module, "sync_datasets", fake_sync)
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "persons-in-dataset": SkillSpec(
                fake_persons,
                frozenset({"community"}),
            ),
            "person-profile": SkillSpec(
                fake_profile,
                frozenset({"community"}),
                depends_on=("persons-in-dataset",),
            ),
        },
        clear=True,
    )

    await bulk_refresh_module.bulk_refresh(
        datasets="sictic-members",
        skills="person-profile",
    )

    assert calls == [
        ("sync", ("sictic-members",), True),
        ("persons-in-dataset", "sictic-members"),
        ("person-profile", "sictic-members"),
    ]


@pytest.mark.asyncio
async def test_failure_continues_and_transitively_skips_dependants(
    mock_env,
    mocker,
    caplog,
):
    calls = []

    async def fake_sync(datasets, raise_on_error=False):
        return []

    async def fail_root(dataset):
        calls.append(("root", dataset))
        raise ValueError("root exploded")

    async def dependent(dataset):
        calls.append(("dependent", dataset))

    async def transitive(dataset):
        calls.append(("transitive", dataset))

    async def unrelated(dataset):
        calls.append(("unrelated", dataset))

    location = dataset_location_for_domain("members", "community")
    get_storage().mkdir(location.raw_rel)
    mocker.patch.object(bulk_refresh_module, "sync_datasets", fake_sync)
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "root": SkillSpec(fail_root, frozenset({"community"})),
            "dependent": SkillSpec(
                dependent,
                frozenset({"community"}),
                depends_on=("root",),
            ),
            "transitive": SkillSpec(
                transitive,
                frozenset({"community"}),
                depends_on=("dependent",),
            ),
            "unrelated": SkillSpec(unrelated, frozenset({"community"})),
        },
        clear=True,
    )

    with pytest.raises(bulk_refresh_module.BulkRefreshError):
        await bulk_refresh_module.bulk_refresh(
            datasets="members",
            skills="root,unrelated",
        )

    assert sorted(calls) == [("root", "members"), ("unrelated", "members")]
    assert "| members | dependent | skipped: root failed for members |" in caplog.text
    assert "| members | root | failed: root exploded |" in caplog.text
    assert "| members | transitive | skipped: root failed for members |" in caplog.text


@pytest.mark.asyncio
async def test_cross_domain_failure_skips_all_consumers(mock_env, mocker):
    calls = []

    async def fake_sync(datasets, raise_on_error=False):
        return []

    async def fail_investor(dataset):
        calls.append(("investor-profile", dataset))
        raise RuntimeError("profile failed")

    async def expert(dataset):
        calls.append(("expert-search", dataset))

    for name, domain in (
        ("members", "community"),
        ("alpha", "startups"),
        ("beta", "startups"),
    ):
        get_storage().mkdir(dataset_location_for_domain(name, domain).raw_rel)
    mocker.patch.object(bulk_refresh_module, "sync_datasets", fake_sync)
    mocker.patch(
        "lib.startups.sources.ensure_startup_dataset",
        side_effect=lambda name, **_: SimpleNamespace(dataset_slug=name),
    )
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "investor-profile": SkillSpec(
                fail_investor,
                frozenset({"community"}),
            ),
            "expert-search": SkillSpec(
                expert,
                frozenset({"startups"}),
                depends_on=("investor-profile",),
            ),
        },
        clear=True,
    )

    with pytest.raises(bulk_refresh_module.BulkRefreshError):
        await bulk_refresh_module.bulk_refresh(
            datasets="members,alpha,beta",
            skills="expert-search",
        )

    assert calls == [("investor-profile", "members")]


@pytest.mark.asyncio
async def test_strict_scope_uses_cached_cross_domain_dependency(mock_env, mocker):
    calls = []

    async def fake_sync(datasets, raise_on_error=False):
        return []

    async def investor(dataset):
        calls.append(("investor-profile", dataset))

    async def expert(dataset):
        calls.append(("expert-search", dataset))

    get_storage().mkdir(dataset_location_for_domain("alpha", "startups").raw_rel)
    mocker.patch.object(bulk_refresh_module, "sync_datasets", fake_sync)
    mocker.patch(
        "lib.startups.sources.ensure_startup_dataset",
        return_value=SimpleNamespace(dataset_slug="alpha"),
    )
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "investor-profile": SkillSpec(
                investor,
                frozenset({"community"}),
            ),
            "expert-search": SkillSpec(
                expert,
                frozenset({"startups"}),
                depends_on=("investor-profile",),
            ),
        },
        clear=True,
    )

    await bulk_refresh_module.bulk_refresh(
        datasets="alpha",
        skills="expert-search",
    )

    assert calls == [("expert-search", "alpha")]


@pytest.mark.asyncio
async def test_ingestion_failure_isolated_to_its_dataset(mock_env, mocker, caplog):
    calls = []

    async def fake_sync(datasets, raise_on_error=False):
        if datasets == ["broken"]:
            raise RuntimeError("cannot ingest")

    async def skill(dataset):
        calls.append(dataset)

    for name in ("broken", "healthy"):
        get_storage().mkdir(
            dataset_location_for_domain(name, "community").raw_rel
        )
    mocker.patch.object(bulk_refresh_module, "sync_datasets", fake_sync)
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {"profile": SkillSpec(skill, frozenset({"community"}))},
        clear=True,
    )

    with pytest.raises(bulk_refresh_module.BulkRefreshError):
        await bulk_refresh_module.bulk_refresh(
            datasets="broken,healthy",
            skills="profile",
        )

    assert calls == ["healthy"]
    assert "| broken | pre-ingestion | failed: cannot ingest |" in caplog.text
    assert "| broken | profile | skipped: pre-ingestion failed for broken |" in caplog.text


@pytest.mark.asyncio
async def test_independent_jobs_run_concurrently(mock_env, mocker):
    active = 0
    maximum_active = 0

    async def fake_sync(datasets, raise_on_error=False):
        return []

    async def skill(dataset):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    get_storage().mkdir(
        dataset_location_for_domain("members", "community").raw_rel
    )
    mocker.patch.object(bulk_refresh_module, "sync_datasets", fake_sync)
    mocker.patch.dict(
        bulk_refresh_module.SKILL_REGISTRY,
        {
            "one": SkillSpec(skill, frozenset({"community"})),
            "two": SkillSpec(skill, frozenset({"community"})),
        },
        clear=True,
    )

    await bulk_refresh_module.bulk_refresh(datasets="members")

    assert maximum_active == 2
