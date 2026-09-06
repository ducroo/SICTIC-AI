from __future__ import annotations

import asyncio
import importlib
import json
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


def _captable_extraction(document: str) -> dict:
    """A minimal, internally consistent cap-table extraction (stage 5)."""
    return {
        "document": document,
        "dataset": "example-startup",
        "as_of_date": {"value": "2026-06-30", "quote": "as of 30 June 2026"},
        "share_classes": [
            {"id": "common", "name": "Common", "nominal_value": 0.10,
             "votes_per_share": 1},
        ],
        "stakeholders": [
            {"name": "Jane Doe", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 600_000}],
             "diluted_count": 600_000, "invested_amount": 60_000},
            {"name": "Fixture Angels", "kind": "entity", "role": "investor",
             "holdings": [{"class_id": "common", "count": 300_000}],
             "diluted_count": 300_000, "invested_amount": 300_000},
            {"name": "Treasury", "kind": "treasury", "role": "company",
             "holdings": [{"class_id": "common", "count": 50_000}],
             "diluted_count": None},
            {"name": "ESOP", "kind": "pool", "role": "employee",
             "holdings": [], "diluted_count": 100_000},
        ],
        "pools": [
            {"kind": "esop", "label": "ESOP 2025", "total": 100_000,
             "granted": 40_000, "unallocated": 60_000},
        ],
        "totals": {
            "by_class": [{"class_id": "common", "issued_total": 950_000}],
            "diluted_total": 1_000_000,
            "quote": "Total 950,000 / fully diluted 1,000,000",
        },
        "fully_diluted_definition": {
            "value": "full_pools",
            "quote": "fully diluted including the full ESOP",
        },
        "assumptions": [],
    }


def _captable_snapshot() -> dict:
    """A stored snapshot (stage 7 output) for the analysis smoke."""
    extraction = _captable_extraction("fixture.md")
    return {
        "dataset": "example-startup",
        "as_of_date": "2026-06-30",
        "generated_at": "2026-09-06T00:00:00+00:00",
        "tool_version": "captable_build/test",
        "sources": [
            {"doc": "fixture.md", "class": "current_cap_table",
             "date": "2026-06-30"},
        ],
        "share_classes": extraction["share_classes"],
        "stakeholders": extraction["stakeholders"],
        "pools": extraction["pools"],
        "totals": extraction["totals"],
        "fully_diluted_definition": extraction["fully_diluted_definition"],
        "register": None,
        "pool_documents": [],
        "convertibles": [],
        "convertible_failures": [],
        "aggregation": {},
        "assessment": [],
        "validation": [],
        "assumptions": [],
        "diligence_questions": [],
    }


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
    InsightFile(
        fixtures.startup,
        "dd_checks",
        "manual",
    ).save(
        "# M&A Due Diligence Checks\n\n"
        "| No | Line-Item | Status | Summary | Concerns |\n"
        "|---|---|---|---|---|\n"
        "| 4.1.3 | Cash Position | Not Found | Current cash is not verified. | "
        "Can cash be verified? |\n"
    )
    get_storage().write_text(
        "storage/community/sictic-members/datasets/track-record/jane-doe.md",
        "Invested in fixture startups.",
    )
    startup_location = dataset_location_for_domain(fixtures.startup, "startups")
    get_storage().mkdir(f"{startup_location.insights_rel}/captable/snapshots")
    get_storage().write_text(
        f"{startup_location.insights_rel}/captable/latest.json",
        json.dumps(_captable_snapshot()),
    )

    yield fixtures
    reset_storage_singleton()


@pytest.fixture
def mocked_skill_boundaries(monkeypatch, skill_fixture_storage):
    fixtures = skill_fixture_storage

    async def fake_sync_datasets(*_args, **_kwargs):
        return []

    async def fake_dataset_chat(*_args, **_kwargs):
        return '{"status": "Found", "summary": "Fixture answer", "concerns": "None"}'

    async def fake_dataset_chat_json(*_args, **kwargs):
        schema = kwargs["schema"]
        properties = schema.get("properties", {})
        if "path" in properties:
            return {
                "path": "fixture.md",
                "document_match": "High",
                "concerns": [],
                "paths_for_alternative_candidates": [],
                "selection_reason": "Fixture substantive SHA.",
            }
        if "industry_type" in properties:
            return {
                "industry_type": "general",
                "confidence": 80,
                "evidence": ["Fixture company evidence."],
            }
        if "names" in properties:
            return {"names": [fixtures.person_name]}
        raise AssertionError("Unexpected dataset-chat JSON schema")

    async def fake_structured_audit_chat(*_args, **kwargs):
        schema = kwargs["schema"]
        statuses = schema.get("properties", {}).get("status", {}).get("enum", [])
        status = (
            "balanced"
            if "balanced" in statuses
            else "Pass"
            if "Pass" in statuses
            else "Assessed"
            if "Assessed" in statuses
            else "Fine"
        )
        return {
            "status": status,
            "rationale": "Fixture evidence",
            "source_documents": ["fixture.md"],
            "proposed_next_steps_and_questions": [],
        }

    async def fake_llm_chat(*_args, **_kwargs):
        return "Fixture LLM profile."

    async def fake_generate_json(_prompt, schema, reviewer=None):
        properties = schema.get("properties", {})
        if "rankings" in properties:
            keys = properties["rankings"]["items"]["properties"][
                "template_key"
            ]["enum"]
            result = {
                "rankings": [
                    {
                        "template_key": key,
                        "rationale_for_rank": "Fixture ranking rationale.",
                    }
                    for key in keys
                ]
            }
        elif "proposed_action" in properties:
            result = {
                "proposed_action": properties["proposed_action"]["enum"][0],
                "rationale": "Complete.",
                "eligibility_concerns": [],
                "missing_or_inconsistent_information": [],
            }
        else:
            raise AssertionError("Unexpected generated JSON schema")
        return reviewer(result).output if reviewer else result

    async def fake_ranking_persons(*_args, **_kwargs):
        return (
            "| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |\n"
            "|---|---|---|---|---|\n"
            "| 1 | Jane Doe | jane@example.com | jane-doe | Fixture match |"
        )

    async def fake_startup_profile(startup, *_args, **_kwargs):
        insight = InsightFile(startup, "startup_profile", "manual")
        if not insight.exists():
            insight.save("# Fixture Startup Profile\n\nExample traction and market.")
        return [insight]

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

    def fake_compile_startup_profiles(startup_profiles):
        return {
            profile.dataset: "# Fixture startup profile."
            for profile in startup_profiles
        }

    async def fake_startup_profiles_from_insight(*_args, **_kwargs):
        _create_dataset("available-startup-profiles", "generated")
        insight = InsightFile(
            fixtures.startup,
            "startup_profile",
            "manual",
        )
        if not insight.exists():
            insight.save("# Fixture Startup Profile")
        return [insight]

    async def fake_generate_report(*_args, **_kwargs):
        return (
            "# Startup Suggestions for Jane Doe\n\n"
            "| Startup | Rationale |\n"
            "|---|---|\n"
            "| example-startup | Fixture rationale |"
        )

    def fake_load_investor_profiles(*_args, **_kwargs):
        return {
            fixtures.person_linkedin_id: "# Jane Doe\n\nInvestor fixture."
        }

    async def fake_ensure_startup_dataset(startup, **_kwargs):
        return SimpleNamespace(dataset_slug="example-startup", dataset_exists=True)

    class FakeSubmissionDealumAdapter:
        dealroom_id = "test"

        def is_configured(self):
            return True

        def list_applications(self):
            return [
                {
                    "id": 1,
                    "name": "example-startup",
                    "code": "EXAMPLE-1",
                    "step": "Application",
                }
            ]

    people_discovery = importlib.import_module("lib.people.discovery")
    startup_sources = importlib.import_module("lib.startups.sources")
    advocates_mod = importlib.import_module("skills.advocates.advocates")
    batch_audit_engine_mod = importlib.import_module("lib.batch_audit.engine")
    submission_ready_mod = importlib.import_module(
        "skills.submission_ready.submission_ready"
    )
    dataset_chat_mod = importlib.import_module("skills.dataset_chat.dataset_chat")
    dd_checks_mod = importlib.import_module("skills.dd_checks.dd_checks")
    dd_priorities_mod = importlib.import_module(
        "skills.dd_priorities.dd_priorities"
    )
    deep_dive_invitation_mod = importlib.import_module(
        "skills.deep_dive_invitation.deep_dive_invitation"
    )
    sha_review_mod = importlib.import_module("skills.sha_review.sha_review")
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
    suggested_startups_inputs = importlib.import_module(
        "skills.suggested_startups.inputs"
    )
    team_profile_mod = importlib.import_module("skills.team_profile.team_profile")
    team_profile_revised_mod = importlib.import_module(
        "skills.team_profile_revised.team_profile_revised"
    )
    monkeypatch.setattr(
        team_profile_revised_mod, "ensure_startup_dataset", fake_ensure_startup_dataset
    )
    monkeypatch.setattr(team_profile_revised_mod, "startup_profile", fake_startup_profile)
    monkeypatch.setattr(team_profile_revised_mod, "generate_markdown", fake_llm_chat)
    persons_skill = importlib.import_module("skills.persons_in_dataset.persons_in_dataset")
    monkeypatch.setattr(persons_skill, "dataset_chat_json", fake_dataset_chat_json)
    monkeypatch.setattr(persons_skill, "LinkedInResolver", FakeLinkedInResolver)


    monkeypatch.setattr(startup_sources, "ensure_startup_dataset", fake_ensure_startup_dataset)
    monkeypatch.setattr(people_discovery, "persons_in_dataset", fake_persons_in_dataset)
    monkeypatch.setattr(
        suggested_startups_inputs,
        "persons_in_dataset",
        fake_persons_in_dataset,
    )

    for module in [
        startup_profile_mod,
        startup_traction_mod,
        person_profile_mod,
        team_profile_mod,
        team_profile_revised_mod,
        dd_checks_mod,
        sha_review_mod,
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
    monkeypatch.setattr(
        dd_checks_mod,
        "dataset_chat_json",
        fake_dataset_chat_json,
    )
    monkeypatch.setattr(
        sha_review_mod,
        "dataset_chat_json",
        fake_dataset_chat_json,
    )
    monkeypatch.setattr(
        dd_priorities_mod,
        "generate_markdown",
        fake_llm_chat,
    )
    monkeypatch.setattr(sha_review_mod, "generate_json", fake_generate_json)
    monkeypatch.setattr(sha_review_mod, "generate_markdown", fake_llm_chat)
    monkeypatch.setattr(
        batch_audit_engine_mod,
        "dataset_chat_json",
        fake_structured_audit_chat,
    )
    monkeypatch.setattr(
        submission_ready_mod,
        "DealumAdapter",
        FakeSubmissionDealumAdapter,
    )
    monkeypatch.setattr(
        submission_ready_mod,
        "import_startup_from_dealum",
        lambda *_args, **_kwargs: SimpleNamespace(
            dataset_slug="example-startup",
            changed=False,
        ),
    )
    monkeypatch.setattr(
        submission_ready_mod,
        "generate_json",
        fake_generate_json,
    )
    monkeypatch.setattr(person_profile_mod, "generate_markdown", fake_llm_chat)
    monkeypatch.setattr(team_profile_mod, "generate_markdown", fake_llm_chat)
    monkeypatch.setattr(team_profile_mod, "dataset_search", fake_dataset_search)
    monkeypatch.setattr(person_profile_mod, "LinkedInResolver", FakeLinkedInResolver)
    monkeypatch.setattr(person_profile_mod, "persons_in_dataset", fake_persons_in_dataset)
    monkeypatch.setattr(person_profile_mod, "build_person_dossier", fake_build_person_dossier)
    monkeypatch.setattr(expert_search_mod, "startup_profile", fake_startup_profile)
    monkeypatch.setattr(potential_investors_mod, "startup_profile", fake_startup_profile)

    async def fake_dealum_import(startup):
        return SimpleNamespace(
            dataset_slug="example-startup",
            dealum_name=startup,
            dealum_url="https://dealum.example/application/1",
            application_path=None,
        )

    async def fake_expert_search(startup, **_kwargs):
        insight = InsightFile(startup, "expert_search", "manual")
        insight.save(await fake_ranking_persons())
        return [insight]

    monkeypatch.setattr(deep_dive_invitation_mod, "dealum_import", fake_dealum_import)
    monkeypatch.setattr(deep_dive_invitation_mod, "startup_profile", fake_startup_profile)
    monkeypatch.setattr(deep_dive_invitation_mod, "expert_search", fake_expert_search)
    monkeypatch.setattr(
        deep_dive_invitation_mod,
        "member_preferences",
        lambda *_args, **_kwargs: [fixtures.person],
    )

    for module in [expert_search_mod, potential_investors_mod, advocates_mod]:
        monkeypatch.setattr(module, "ranking_persons", fake_ranking_persons)

    monkeypatch.setattr(
        suggested_startups_mod,
        "load_startup_profiles",
        fake_startup_profiles_from_insight,
    )
    monkeypatch.setattr(suggested_startups_mod, "compile_startup_profiles", fake_compile_startup_profiles)
    monkeypatch.setattr(suggested_startups_mod, "generate_report", fake_generate_report)
    monkeypatch.setattr(
        suggested_startups_mod,
        "load_investor_profiles",
        fake_load_investor_profiles,
    )

    captable_build_mod = importlib.import_module(
        "skills.captable_build.captable_build"
    )
    captable_analysis_mod = importlib.import_module(
        "skills.captable_analysis.captable_analysis"
    )
    table_extraction_mod = importlib.import_module("lib.captable.table_extraction")

    async def fake_classify_documents(dataset_name):
        return {
            "dataset": dataset_name,
            "documents": [
                {
                    "filename": "fixture.md",
                    "document_class": "current_cap_table",
                    "confidence": 95,
                    "as_of_date": "2026-06-30",
                    "language": "en",
                    "rationale": "Fixture cap table.",
                }
            ],
        }

    async def fake_extract_captable(_dataset_name, filename, _document_text):
        return _captable_extraction(filename)

    monkeypatch.setattr(captable_build_mod, "classify_documents", fake_classify_documents)
    monkeypatch.setattr(table_extraction_mod, "extract_captable", fake_extract_captable)
    monkeypatch.setattr(captable_analysis_mod, "generate_markdown", fake_llm_chat)

    return fixtures
