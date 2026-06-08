import pytest
from importlib import import_module

advocates_module = import_module("skills.advocates.advocates")
expert_search_module = import_module("skills.expert_search.expert_search")
potential_investors_module = import_module(
    "skills.potential_investors.potential_investors"
)


async def _fake_startup_profile(*args, **kwargs):
    return "Startup profile", "profile.md"


async def _fake_ranking_persons(*args, **kwargs):
    return "Ranked result"


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
    mocker.patch.object(
        module,
        "check_insight_refresh",
        return_value=(True, None, None),
    )
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
    hydrate = mocker.patch.object(module, "dataset_from_insight")
    ranking = mocker.patch.object(
        module,
        "ranking_persons",
        side_effect=_fake_ranking_persons,
    )

    result = await getattr(module, func_name)(*args)

    assert result == "Ranked result"
    hydrate.assert_awaited_once_with(
        insight_name="investor_profile",
        source_dataset="sictic-members",
    )
    assert ranking.await_args.kwargs["dataset_name"] == "sictic-members-investor-profile"
