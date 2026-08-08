import pytest
from importlib import import_module

from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain

advocates_module = import_module("skills.advocates.advocates")
expert_search_module = import_module("skills.expert_search.expert_search")
potential_investors_module = import_module(
    "skills.potential_investors.potential_investors"
)


async def _fake_startup_profile(*args, **kwargs):
    class FakeStartupProfileInsight:
        def content(self):
            return "Startup profile"

    return [FakeStartupProfileInsight()]


async def _fake_ranking_persons(*args, **kwargs):
    return "Ranked result"


def _create_route_datasets(module):
    if module is advocates_module:
        location = dataset_location_for_domain("sictic-members", "community")
    else:
        location = dataset_location_for_domain("example-startup", "startups")
    get_storage().mkdir(location.raw_rel)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module,func_name,config_key,args",
    [
        (
            expert_search_module,
            "expert_search",
            "expert_search",
            ("example-startup",),
        ),
        (
            potential_investors_module,
            "potential_investors",
            "potential_investors",
            ("example-startup",),
        ),
        (
            advocates_module,
            "advocates",
            "advocates",
            ("example-event", "Event description"),
        ),
    ],
)
async def test_ranking_skill_uses_investor_profile_dataset(
    mock_env,
    mocker,
    module,
    func_name,
    config_key,
    args,
):
    _create_route_datasets(module)
    mocker.patch.object(module.InsightFile, "find", return_value=None)
    mocker.patch.object(module.InsightFile, "save")
    mocker.patch.object(module, "sync_datasets")
    if hasattr(module, "startup_profile"):
        mocker.patch.object(
            module,
            "startup_profile",
            side_effect=_fake_startup_profile,
        )
    mocker.patch.object(
        module,
        "config_load",
        return_value={config_key: {"objective": "Objective {{startup_profile}}{{overview_event}}"}},
    )
    hydrate = mocker.patch.object(
        module,
        "dataset_from_insight",
    )
    ranking = mocker.patch.object(
        module,
        "ranking_persons",
        side_effect=_fake_ranking_persons,
    )

    result = await getattr(module, func_name)(*args)

    assert len(result) == 1
    assert result[0].skill == func_name
    hydrate.assert_awaited_once_with(
        "sictic-members-investor-profile",
        ["sictic-members"],
        "investor_profile",
    )
    assert ranking.await_args.kwargs["dataset_name"] == "sictic-members-investor-profile"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module,func_name,args,targets,excludes",
    [
        (
            expert_search_module,
            "expert_search",
            ("example-startup",),
            {"target_experts": ["Urs Gubser"]},
            {"exclude_experts": ["jane@sictic.ch"]},
        ),
        (
            potential_investors_module,
            "potential_investors",
            ("example-startup",),
            {"target_investors": ["Urs Gubser"]},
            {"exclude_investors": ["jane@sictic.ch"]},
        ),
        (
            advocates_module,
            "advocates",
            ("example-event", "Event description"),
            {"target_members": ["Urs Gubser"]},
            {"exclude_members": ["jane@sictic.ch"]},
        ),
    ],
)
async def test_ranking_skills_pass_person_references_without_slugifying(
    mock_env,
    mocker,
    module,
    func_name,
    args,
    targets,
    excludes,
):
    _create_route_datasets(module)
    mocker.patch.object(module.InsightFile, "find", return_value=None)
    mocker.patch.object(module.InsightFile, "save")
    mocker.patch.object(module, "sync_datasets")
    if hasattr(module, "startup_profile"):
        mocker.patch.object(module, "startup_profile", side_effect=_fake_startup_profile)
    config_key = func_name
    mocker.patch.object(
        module,
        "config_load",
        return_value={
            config_key: {
                "objective": "Objective {{startup_profile}}{{overview_event}}"
            }
        },
    )
    mocker.patch.object(module, "dataset_from_insight")
    ranking = mocker.patch.object(
        module,
        "ranking_persons",
        side_effect=_fake_ranking_persons,
    )

    await getattr(module, func_name)(*args, **targets, **excludes)

    assert ranking.await_args.kwargs["candidates"] == ["Urs Gubser"]
    assert ranking.await_args.kwargs["optout"] == ["jane@sictic.ch"]
