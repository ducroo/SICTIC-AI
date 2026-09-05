from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.batch_audit.checklist import parse_checklist
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import load_repository_config
from lib.insights import InsightFile
from lib.people.model import Person
from lib.storage import get_storage

ROOT = Path(__file__).resolve().parents[2]


def _indexed_dataset() -> None:
    location = dataset_location_for_domain("acme", "startups")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()


def test_revised_checklists_account_for_all_supplied_ids(mock_env):
    config = load_repository_config("team_profile_revised")
    original = (ROOT / "skills/team_profile_revised/references/original_team_questions.md").read_text()
    expected = set(re.findall(r"\*\*(Q\d{3}):", original))
    expected |= {f"N{i:03}" for i in range(1, 7)}
    expected |= {f"R{i:03}" for i in range(1, 11)}
    framework = {"Q010", "Q029", "Q030", "Q126", "Q128", "Q142"}
    represented = []
    numbers = []
    for markdown in config["checklists"].values():
        checklist = parse_checklist(markdown)
        for chapter in checklist.chapters:
            for check in chapter.checks:
                ids = re.findall(r"\b[QNR]\d{3}\b", check.name)
                assert ids and all(identifier in check.description for identifier in ids)
                assert check.keywords
                represented.extend(ids)
                numbers.append(check.number)
    assert len(config["checklists"]) == 4
    assert len(numbers) == len(set(numbers)) == 40
    assert len(represented) == len(set(represented))
    assert set(represented).isdisjoint(framework)
    assert set(represented) | framework == expected
    mapping = (ROOT / "skills/team_profile_revised/references/checklist_decisions.md").read_text()
    assert set(re.findall(r"^\| ([QNR]\d{3}) \|", mapping, re.M)) == expected


@pytest.fixture
def revised_runtime(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    module = importlib.import_module("skills.team_profile_revised.team_profile_revised")
    chat = importlib.import_module("skills.dataset_chat.dataset_chat")
    _indexed_dataset()
    startup = InsightFile("acme", "startup_profile", "manual")
    startup.save("Hardware startup. Source: deck.pdf — page 2.")
    persons = [
        Person(full_name="Zoe Advisor", person_profile_markdown="Advisor, not a founder."),
        Person(full_name="Amy Founder", person_profile_markdown="Active founder. Source: cv.pdf — page 1."),
    ]
    monkeypatch.setattr(module, "ensure_startup_dataset", AsyncMock(return_value=SimpleNamespace(dataset_slug="acme")))
    monkeypatch.setattr(module, "sync_datasets", AsyncMock())
    startup_call = AsyncMock(return_value=[startup])
    person_call = AsyncMock(return_value=persons)
    monkeypatch.setattr(module, "startup_profile", startup_call)
    monkeypatch.setattr(module, "person_profile_as_person_objects", person_call)
    # No new retrieval evidence: the actual batch/chat path must still use the
    # shared profiles, while retaining distinct per-question searches.
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(chat, "dataset_search", search)
    generation = AsyncMock(return_value={
        "status": "Assessed",
        "rationale": "Founder experience is documented (cv.pdf — page 1).",
        "source_documents": ["cv.pdf — page 1"],
        "proposed_next_steps_and_questions": [],
    })
    monkeypatch.setattr(chat, "generate_json", generation)
    synthesis = AsyncMock(return_value="## 1. Individual Founder Quality\n\nFounder evidence [Q005]: cv.pdf — page 1.")
    monkeypatch.setattr(module, "generate_markdown", synthesis)
    return SimpleNamespace(
        module=module, startup=startup, startup_call=startup_call,
        person_call=person_call, search=search, generation=generation,
        synthesis=synthesis, persons=persons,
    )


@pytest.mark.asyncio
async def test_revised_pipeline_shares_profiles_and_reuses_caches(revised_runtime):
    runtime = revised_runtime
    [result] = await runtime.module.team_profile_revised("ACME")
    runtime.startup_call.assert_awaited_once_with("acme")
    runtime.person_call.assert_awaited_once_with(
        "acme", names=None, allow_public_sources=False, assess_founder_traits=True,
    )
    assert result.skill == "team_profile_revised"
    assert "cv.pdf — page 1" in result.content()
    assert runtime.search.await_count == runtime.generation.await_count == 40
    prefixes = {call.kwargs["cacheable_prompt_prefix"] for call in runtime.generation.await_args_list}
    assert len(prefixes) == 1
    prefix = prefixes.pop()
    assert prefix.index("Hardware startup") < prefix.index("Amy Founder") < prefix.index("Zoe Advisor")
    assert "CURRENT CHECK" not in prefix
    assert all("CURRENT CHECK" in call.args[0] for call in runtime.generation.await_args_list)
    summary_prompt = runtime.synthesis.await_args.args[0]
    assert summary_prompt.count("### CATEGORY AUDIT:") == 4
    assert '"source_documents"' in summary_prompt
    assert "Q005" in summary_prompt and "R007" in summary_prompt
    runtime.synthesis.assert_awaited_once()

    [cached] = await runtime.module.team_profile_revised("ACME")
    assert cached.path == result.path
    assert runtime.generation.await_count == 40
    assert runtime.synthesis.await_count == 1

    # Profile content may change independently of the indexed dataset revision.
    runtime.startup.save("Changed milestone. Source: deck.pdf — page 3.")
    await runtime.module.team_profile_revised("ACME")
    assert runtime.generation.await_count == 80
    assert runtime.synthesis.await_count == 2


@pytest.mark.asyncio
async def test_technical_retrieval_failures_block_synthesis_and_can_resume(revised_runtime):
    runtime = revised_runtime
    async def search(_dataset, queries, **_kwargs):
        if queries[0].startswith("Q005:"):
            raise RuntimeError("retrieval unavailable")
        return []
    runtime.search.side_effect = search
    with pytest.raises(RuntimeError, match="technical failures.*retrieval unavailable"):
        await runtime.module.team_profile_revised("acme")
    runtime.synthesis.assert_not_awaited()
    assert not InsightFile("acme", "team_profile_revised", "ollama/test_model:1b").exists()

    runtime.search.side_effect = None
    await runtime.module.team_profile_revised("acme")
    runtime.synthesis.assert_awaited_once()
    # Successful category artifacts survive; only the failed category is rerun.
    assert runtime.search.await_count == 54


@pytest.mark.asyncio
async def test_empty_synthesis_is_not_saved(revised_runtime):
    runtime = revised_runtime
    runtime.synthesis.return_value = " \n "
    with pytest.raises(ValueError, match="empty response"):
        await runtime.module.team_profile_revised("acme")
    assert not InsightFile("acme", "team_profile_revised", "ollama/test_model:1b").exists()


@pytest.mark.asyncio
async def test_no_discovered_people_still_runs_checks(revised_runtime):
    runtime = revised_runtime
    runtime.person_call.return_value = []
    await runtime.module.team_profile_revised("acme")
    assert runtime.search.await_count == 40
    assert "No related persons were identified" in runtime.generation.await_args.kwargs["cacheable_prompt_prefix"]


@pytest.mark.asyncio
async def test_harness_dispatches_revised_command(revised_runtime):
    from skills.harness.harness import dispatch_command

    output = await dispatch_command('/team_profile_revised "ACME"')
    assert "Error:" not in output
    assert "Founder evidence" in output


def test_bulk_refresh_revised_waits_for_person_profiles():
    from skills.skill_registry import expand_skill_dependencies

    assert expand_skill_dependencies(["team-profile-revised"]) == [
        "startup-profile", "persons-in-dataset", "person-profile", "team-profile-revised",
    ]
