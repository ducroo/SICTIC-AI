from importlib import import_module

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage


@pytest.fixture(params=["expert_search", "potential_investors"])
def startup_ranking(request, mock_env, monkeypatch, mocker):
    name = request.param
    module = import_module(f"skills.{name}.{name}")
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    for dataset, domain in [("example-startup", "startups"), ("sictic-members", "community")]:
        location = dataset_location_for_domain(dataset, domain)
        get_storage().mkdir(location.raw_rel)
        manifest = IngestionManifest(get_storage(), location.parsed_rel)
        manifest.indexed_dataset_revision = "unchanged-source-revision"
        manifest.save()
    profile = InsightFile("example-startup", "startup_profile", "manual")
    profile.save("Startup profile version one")
    get_profile = mocker.patch.object(module, "startup_profile", return_value=[profile])
    mocker.patch.object(
        module, "load_repository_config",
        return_value={name: {"objective": "Rank against {{startup_profile}}"}},
    )

    async def rank(**kwargs):
        return kwargs["objective"]

    ranking = mocker.patch.object(module, "ranking_persons", side_effect=rank)
    return getattr(module, name), profile, get_profile, ranking


@pytest.mark.asyncio
async def test_startup_profile_edit_invalidates_ranking_without_reindexing(startup_ranking):
    run, profile, get_profile, ranking = startup_ranking
    [first] = await run("example-startup")
    assert first.is_reusable()

    [cached] = await run("example-startup")
    assert cached.path == first.path
    assert ranking.await_count == 1

    profile.save("Startup profile version two")
    [updated] = await run("example-startup")
    assert updated.path == first.path
    assert updated.content() == "Rank against Startup profile version two"
    assert ranking.await_count == 2
    assert get_profile.await_count == 3
    assert updated.source_datasets == ["example-startup", "sictic-members"]

    await run("example-startup")
    assert ranking.await_count == 2


@pytest.mark.asyncio
async def test_manual_ranking_precedes_dependency_generation(startup_ranking):
    run, _profile, get_profile, ranking = startup_ranking
    manual = InsightFile("example-startup", run.__name__, "manual")
    manual.save("Manually reviewed ranking")
    get_profile.side_effect = RuntimeError("Profile service unavailable")

    [result] = await run("example-startup")

    assert result.path == manual.path
    assert result.content() == "Manually reviewed ranking"
    get_profile.assert_not_awaited()
    ranking.assert_not_awaited()
