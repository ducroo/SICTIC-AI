from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.people.model import Person
from lib.storage import get_storage, reset_storage_singleton


@dataclass(frozen=True)
class SkillHarnessFixtures:
    startup: str = "example-startup"
    community: str = "sictic-members"
    generated: str = "sictic-members-investor-profile"
    person_name: str = "Jane Doe"
    person_linkedin_id: str = "jane-doe"

    @property
    def person(self) -> Person:
        return Person(
            full_name=self.person_name,
            linkedin_id=self.person_linkedin_id,
            email_addresses=["jane@example.com"],
            linkedin_profile={"headline": "Angel investor"},
        )


def _create_dataset(name: str, domain: str) -> None:
    storage = get_storage()
    location = dataset_location_for_domain(name, domain)
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.parsed_rel)
    storage.mkdir(location.insights_rel)
    storage.write_text(
        f"{location.raw_rel}/fixture.md",
        f"# {name}\n\nLocal fixture dataset for skill harness tests.\n",
    )
    storage.write_text(
        f"{location.parsed_rel}/fixture.md",
        f"# Parsed {name}\n\nJane Doe is connected to {name}.\n",
    )


@pytest.fixture
def skill_fixture_storage(monkeypatch, tmp_path) -> SkillHarnessFixtures:
    storage_root = tmp_path / "local-storage"
    data_root = tmp_path / "local-data"
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_root))
    monkeypatch.setenv("LOCAL_DATA_PATH", str(data_root))
    monkeypatch.setenv("DEALUM_API_KEY", "")
    monkeypatch.setenv("DEALUM_DEALROOM_ID", "")
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    reset_storage_singleton()

    fixtures = SkillHarnessFixtures()
    _create_dataset(fixtures.startup, "startups")
    _create_dataset(fixtures.community, "community")
    _create_dataset(fixtures.generated, "generated")

    InsightFile(
        fixtures.community,
        "person_profile",
        "ollama/test_model:1b",
        identifier=fixtures.person_linkedin_id,
        subdir=True,
    ).save("# Jane Doe\n\nExperienced angel investor.")
    get_storage().write_text(
        "storage/community/sictic-members/datasets/track-record/jane-doe.md",
        "Invested in fixture startups.",
    )

    yield fixtures
    reset_storage_singleton()


@pytest.fixture(autouse=True)
def forbid_cloud_sync(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("skill harness tests must not invoke Google Drive sync")

    import gdrive_sync.client as gdrive_client
    import lib.storage_gdrive as storage_gdrive

    monkeypatch.setattr(gdrive_client.GDriveSync, "push", blocked)
    monkeypatch.setattr(gdrive_client.GDriveSync, "pull", blocked)
    monkeypatch.setattr(gdrive_client.GDriveSync, "sync", blocked)
    monkeypatch.setattr(storage_gdrive.GoogleDriveStorage, "_ensure_service", blocked)
    monkeypatch.setattr(storage_gdrive.GoogleDriveStorage, "_load_or_authorize", blocked)


@pytest.fixture
def mocked_skill_boundaries(monkeypatch, skill_fixture_storage):
    fixtures = skill_fixture_storage

    async def fake_sync_datasets(*_args, **_kwargs):
        return []

    async def fake_dataset_chat(*_args, **_kwargs):
        return '{"status": "Found", "summary": "Fixture answer", "concerns": "None"}'

    async def fake_submission_dataset_chat(*_args, **_kwargs):
        return (
            '{"judgment": "Pass", "assessment": "Fixture evidence", '
            '"source_documents": ["Dealum Application — fixture"], '
            '"proposed_next_step": "No action"}'
        )

    async def fake_llm_chat(*_args, **_kwargs):
        return "Fixture LLM profile."

    async def fake_ranking_persons(*_args, **_kwargs):
        return "| Rank | Person | Rationale |\n|---|---|---|\n| 1 | Jane Doe | Fixture match |"

    async def fake_hydrate_dataset_from_insights(*_args, **_kwargs):
        return SimpleNamespace(dataset_name=fixtures.generated, written=1)

    async def fake_startup_profile(startup, *_args, **_kwargs):
        insight = InsightFile(startup, "startup_profile", "manual")
        if not insight.exists():
            insight.save("# Fixture Startup Profile\n\nExample traction and market.")
        return insight.content(), insight.path

    async def fake_investor_profile(*_args, **_kwargs):
        return SimpleNamespace(source_dataset=fixtures.community, person_profiles=1, written=1)

    class FakeLinkedInResolver:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_profiles(self, persons):
            return [
                Person(
                    full_name=person.full_name or fixtures.person_name,
                    linkedin_id=person.linkedin_id or fixtures.person_linkedin_id,
                    email_addresses=person.email_addresses or ["jane@example.com"],
                    linkedin_profile={"headline": "Fixture investor"},
                )
                for person in persons
            ]

        def get_all_persons(self):
            return [fixtures.person_name]

    def fake_persons_in_dataset(*_args, **_kwargs):
        return [fixtures.person]

    async def fake_build_person_dossier(*_args, **_kwargs):
        return [], []

    async def fake_dataset_search(*_args, **_kwargs):
        return []

    async def fake_compile_startup_profiles(startups):
        return {startup: f"# {startup}\n\nFixture startup profile." for startup in startups}

    async def fake_process_single_investor(*_args, **_kwargs):
        return ["| example-startup | Fixture rationale |"]

    def fake_read_investor_profiles(*_args, **_kwargs):
        return {fixtures.person_name: "# Jane Doe\n\nInvestor fixture."}

    async def fake_ensure_startup_dataset(startup, **_kwargs):
        return SimpleNamespace(dataset_slug="example-startup", dataset_exists=True)

    people_discovery = importlib.import_module("lib.people.discovery")
    startup_sources = importlib.import_module("lib.startups.sources")
    advocates_mod = importlib.import_module("skills.advocates.advocates")
    batch_audit_mod = importlib.import_module("skills.batch_audit.batch_audit")
    submission_ready_mod = importlib.import_module(
        "skills.submission_ready.submission_ready"
    )
    dataset_chat_mod = importlib.import_module("skills.dataset_chat.dataset_chat")
    dd_checks_mod = importlib.import_module("skills.dd_checks.dd_checks")
    expert_search_mod = importlib.import_module("skills.expert_search.expert_search")
    investor_profile_mod = importlib.import_module("skills.investor_profile.investor_profile")
    person_profile_mod = importlib.import_module("skills.person_profile.person_profile")
    potential_investors_mod = importlib.import_module(
        "skills.potential_investors.potential_investors"
    )
    startup_profile_mod = importlib.import_module("skills.startup_profile.startup_profile")
    startup_traction_mod = importlib.import_module("skills.startup_traction.startup_traction")
    suggested_startups_mod = importlib.import_module(
        "skills.suggested_startups.suggested_startups"
    )
    team_profile_mod = importlib.import_module("skills.team_profile.team_profile")

    monkeypatch.setattr(startup_sources, "ensure_startup_dataset", fake_ensure_startup_dataset)
    monkeypatch.setattr(people_discovery, "persons_in_dataset", fake_persons_in_dataset)

    for module in [
        startup_profile_mod,
        startup_traction_mod,
        person_profile_mod,
        team_profile_mod,
        dd_checks_mod,
        submission_ready_mod,
        expert_search_mod,
        potential_investors_mod,
        advocates_mod,
        suggested_startups_mod,
    ]:
        if hasattr(module, "sync_datasets"):
            monkeypatch.setattr(module, "sync_datasets", fake_sync_datasets)

    monkeypatch.setattr(startup_profile_mod, "dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(startup_traction_mod, "dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(dataset_chat_mod, "dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(dd_checks_mod, "dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(batch_audit_mod, "dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(
        submission_ready_mod,
        "dataset_chat",
        fake_submission_dataset_chat,
    )
    monkeypatch.setattr(person_profile_mod, "llm_chat", fake_llm_chat)
    monkeypatch.setattr(team_profile_mod, "llm_chat", fake_llm_chat)
    monkeypatch.setattr(team_profile_mod, "dataset_search", fake_dataset_search)
    monkeypatch.setattr(person_profile_mod, "LinkedInResolver", FakeLinkedInResolver)
    monkeypatch.setattr(person_profile_mod, "persons_in_dataset", fake_persons_in_dataset)
    monkeypatch.setattr(person_profile_mod, "build_person_dossier", fake_build_person_dossier)
    monkeypatch.setattr(expert_search_mod, "startup_profile", fake_startup_profile)
    monkeypatch.setattr(potential_investors_mod, "startup_profile", fake_startup_profile)

    for module in [expert_search_mod, potential_investors_mod, advocates_mod]:
        monkeypatch.setattr(module, "ranking_persons", fake_ranking_persons)
        monkeypatch.setattr(module, "hydrate_dataset_from_insights", fake_hydrate_dataset_from_insights)

    monkeypatch.setattr(suggested_startups_mod, "LinkedInResolver", FakeLinkedInResolver)
    monkeypatch.setattr(suggested_startups_mod, "compile_startup_profiles", fake_compile_startup_profiles)
    monkeypatch.setattr(suggested_startups_mod, "process_single_investor", fake_process_single_investor)
    monkeypatch.setattr(suggested_startups_mod, "investor_profile", fake_investor_profile)
    monkeypatch.setattr(suggested_startups_mod, "read_investor_profiles", fake_read_investor_profiles)

    return fixtures
