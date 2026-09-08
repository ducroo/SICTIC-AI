from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import load_repository_config
from lib.insights import InsightFile
from lib.people import Person
from lib.storage import get_storage


@pytest.fixture
def invitation(monkeypatch, mock_env):
    module = import_module("skills.deep_dive_invitation.deep_dive_invitation")
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    monkeypatch.setattr(module, "llm_model", lambda: "ollama/test_model:1b")
    manifests = {}
    for dataset, domain in [("example-startup", "startups"), ("sictic-members", "community")]:
        location = dataset_location_for_domain(dataset, domain)
        get_storage().mkdir(location.raw_rel)
        manifest = IngestionManifest(get_storage(), location.parsed_rel)
        manifest.indexed_dataset_revision = "revision-one"
        manifest.save()
        manifests[dataset] = manifest

    config = deepcopy(load_repository_config("deep_dive_invitation"))
    monkeypatch.setattr(module, "load_repository_config", lambda *_: config)
    expert = InsightFile("example-startup", "expert_search", "manual")
    expert.save("| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |\n"
                "|---|---|---|---|---|\n")
    dependencies = [
        AsyncMock(return_value=SimpleNamespace(
            dataset_slug="example-startup", dealum_name="Example Startup",
            dealum_url="https://dealum.example/1", application_path=None,
        )),
        AsyncMock(return_value=[]),
        Mock(return_value=[]),
        AsyncMock(return_value=[expert]),
    ]
    for name, dependency in zip(
        ["dealum_import", "startup_profile", "member_preferences", "expert_search"],
        dependencies,
    ):
        monkeypatch.setattr(module, name, dependency)
    return SimpleNamespace(
        run=module.deep_dive_invitation, config=config, manifests=manifests,
        dependencies=dependencies, expert=expert,
    )


def assert_dependencies_not_called(invitation):
    for dependency in invitation.dependencies:
        dependency.assert_not_called()


def reset_dependencies(invitation):
    for dependency in invitation.dependencies:
        dependency.reset_mock()


@pytest.mark.asyncio
async def test_manual_returns_before_dependencies_even_without_indexed_revisions(invitation):
    manual = InsightFile("example-startup", "deep_dive_invitation", "manual")
    manual.save("Human-edited invitation")
    for manifest in invitation.manifests.values():
        manifest.indexed_dataset_revision = ""
        manifest.save()
    for dependency in invitation.dependencies:
        dependency.side_effect = AssertionError("No dependency should run")

    [result] = await invitation.run("Example Startup")

    assert result.path == manual.path
    assert result.content() == "Human-edited invitation"
    assert_dependencies_not_called(invitation)


@pytest.mark.asyncio
async def test_fresh_generated_returns_before_all_dependencies(invitation):
    [first] = await invitation.run("Example Startup")
    assert first.is_reusable()
    assert first.source_datasets == ["example-startup", "sictic-members"]
    reset_dependencies(invitation)
    # Dependency reports are deliberately no longer part of invitation freshness.
    invitation.expert.save("Edited expert report")
    for dependency in invitation.dependencies:
        dependency.side_effect = AssertionError("Cache hit must not run dependencies")

    [result] = await invitation.run("Example Startup")

    assert result.path == first.path
    assert result.content() == first.content()
    assert_dependencies_not_called(invitation)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    "example-startup", "sictic-members", "missing-revision", "template",
    "settings", "founders", "investors",
])
async def test_stale_generated_runs_dependencies(invitation, change):
    [first] = await invitation.run("Example Startup")
    reset_dependencies(invitation)
    kwargs = {}
    if change in invitation.manifests:
        invitation.manifests[change].indexed_dataset_revision = "revision-two"
        invitation.manifests[change].save()
    elif change == "missing-revision":
        invitation.manifests["sictic-members"].indexed_dataset_revision = ""
        invitation.manifests["sictic-members"].save()
    elif change == "template":
        invitation.config["email_template"] += "\nUpdated invitation wording.\n"
    elif change == "settings":
        invitation.config["settings"]["max_experts"] = 9
    else:
        kwargs[change] = [Person(full_name="New Contact", email_addresses=["new@example.com"])]

    [result] = await invitation.run("Example Startup", **kwargs)

    assert result.path == first.path
    for dependency in invitation.dependencies:
        dependency.assert_called_once()
    if change == "template":
        assert "Updated invitation wording." in result.content()


@pytest.mark.asyncio
async def test_locally_known_alias_returns_before_import(invitation, monkeypatch):
    identity = import_module("lib.startups.identity")
    monkeypatch.setattr(identity, "startup_aliases", lambda: {"old-name": "example-startup"})
    manual = InsightFile("example-startup", "deep_dive_invitation", "manual")
    manual.save("Manual invitation")

    [result] = await invitation.run("Old Name")

    assert result.path == manual.path
    assert_dependencies_not_called(invitation)


@pytest.mark.asyncio
async def test_application_code_checks_resolved_dataset_before_other_dependencies(invitation):
    [first] = await invitation.run("Example Startup")
    reset_dependencies(invitation)

    [result] = await invitation.run("ABCD-1234")

    assert result.path == first.path
    invitation.dependencies[0].assert_awaited_once_with("ABCD-1234")
    for dependency in invitation.dependencies[1:]:
        dependency.assert_not_called()


@pytest.mark.asyncio
async def test_application_code_saves_under_resolved_slug_on_cache_miss(invitation):
    [result] = await invitation.run("ABCD-1234")

    assert result.dataset == "example-startup"
    assert result.source_datasets == ["example-startup", "sictic-members"]
    assert result.is_reusable()
    invitation.dependencies[1].assert_awaited_once_with("example-startup")


@pytest.mark.asyncio
async def test_cc_changes_keep_ranking_request_identical_and_filter_before_limit(invitation):
    interested = Person(
        full_name="Interested Member", linkedin_id="interested-member",
        email_addresses=["member@gmail.com", "member@investor.sictic.ch"],
    )
    available = Person(
        full_name="Available Expert", linkedin_id="available-expert",
        email_addresses=["expert@investor.sictic.ch"],
    )
    opted_out = Person(
        full_name="Opted Out", linkedin_id="opted-out",
        email_addresses=["out@investor.sictic.ch"],
        adhoc_data={"member_preferences": {"deep_dive_invitation": "none"}},
    )
    invitation.dependencies[2].return_value = [interested, available, opted_out]
    invitation.config["settings"]["max_experts"] = 1
    invitation.expert.save(
        "| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |\n"
        "|---|---|---|---|---|\n"
        "| 1 | Interested Member | member@investor.sictic.ch | interested-member | Fit |\n"
        "| 2 | Opted Out | out@investor.sictic.ch | opted-out | Fit |\n"
        "| 3 | Available Expert | expert@investor.sictic.ch | available-expert | Fit |\n"
    )

    [first] = await invitation.run("Example Startup", investors=[Person(
        full_name="Interested Member", email_addresses=["member@gmail.com"],
    )])
    first_content = first.content()
    assert "Cc:  \nInterested Member <member@gmail.com>" in first_content
    assert "Bcc:  \nAvailable Expert <expert@investor.sictic.ch>" in first_content
    assert "member@investor.sictic.ch" not in first_content
    assert "out@investor.sictic.ch" not in first_content
    assert "Interested investors with an email in Cc: 1" in first_content
    invitation.dependencies[3].assert_awaited_once_with(
        "example-startup", exclude_experts=["opted-out"], top_k=16,
    )
    first_request = invitation.dependencies[3].await_args

    [second] = await invitation.run("Example Startup")

    assert invitation.dependencies[3].await_count == 2
    assert invitation.dependencies[3].await_args == first_request
    assert "Bcc:  \nInterested Member <member@investor.sictic.ch>" in second.content()
