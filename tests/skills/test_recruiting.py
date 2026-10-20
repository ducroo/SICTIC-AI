import importlib
import json
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from lib.datasets.chunking import build_chunk
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.infrastructure.configuration import load_repository_config
from lib.people.model import Person
from lib.storage import get_storage

CRITERIA = "## Skills\n\n### Spreadsheets\nAssess formulas and pivot tables.\n"
DATASET = "2026-mediamatiker"


def indexed_dataset():
    location = dataset_location_for_domain(DATASET, "community")
    get_storage().mkdir(location.raw_rel)
    manifest = IngestionManifest(get_storage(), location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()


def assessment(score=3):
    return {
        "score": score, "status": "assessed" if score is not None else "unconfirmed",
        "evidence": "Resume page 1", "rationale": "Relevant experience",
        "gaps": "", "interview_question": "",
    }


@pytest.fixture
def workflow(mock_env, monkeypatch):
    indexed_dataset()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    module = importlib.import_module("skills.recruiting.recruiting")
    engine = importlib.import_module("lib.batch_audit.engine")
    alice = Person(
        full_name="Alice Smith", linkedin_id="alice-smith",
        dossier=[build_chunk("Alice spreadsheet experience", "resumes/alice-smith.pdf", 1, 0)],
        linkedin_profile={"fullName": "Alice Smith"},
        person_profile_markdown="Alice profile",
    )
    bob = Person(
        full_name="Bob Jones", email_addresses=["bob@example.com"],
        dossier=[build_chunk("Bob career", "resumes/bob-jones.pdf", 1, 0)],
        person_profile_markdown="Bob profile",
    )
    monkeypatch.setattr(module, "build_person_dossier", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(module, "persons_in_dataset", AsyncMock())
    monkeypatch.setattr(module, "person_profile_as_person_objects", AsyncMock(return_value=[alice, bob]))
    monkeypatch.setattr(module, "generate_markdown", AsyncMock(return_value=CRITERIA))
    monkeypatch.setattr(module, "generate_json", AsyncMock(return_value={
        alice.identifier: {"rank": 2, "rationale": "Strong spreadsheet evidence."},
        bob.identifier: {"rank": 1, "rationale": "Needs clarification."},
    }))
    monkeypatch.setattr(engine, "dataset_chat_json", AsyncMock(side_effect=AssertionError("No retrieval")))
    monkeypatch.setattr(engine, "generate_json", AsyncMock(return_value=assessment()))
    return module, engine, alice, bob


@pytest.mark.asyncio
async def test_harness_dispatch_runs_recruiting_workflow(workflow):
    from skills.harness.harness import dispatch_command

    output = await dispatch_command(f'/recruiting {DATASET} --criteria "Job advert"')

    assert "Error:" not in output
    assert "Bob Jones" in output
    assert "Alice Smith" in output
    assert InsightFile(DATASET, "recruiting", "ollama/test_model:1b").exists()


@pytest.mark.asyncio
async def test_workflow_isolates_people_and_reuses_artifacts(workflow):
    module, engine, alice, bob = workflow
    result = await module.recruiting(DATASET, "Job advert")
    assert all(isinstance(item, InsightFile) for item in result)
    assert len(result) == 6
    assert result[0].filename == "job-criteria-2026-mediamatiker-test-model-1b.md"
    assert result[-1].filename == "recruiting-2026-mediamatiker-test-model-1b.md"
    audits = [item for item in result if item.extension == "json"]
    assert len({item.path for item in audits}) == 2
    assert "recruiting-alice-smith" in audits[0].filename
    assert "bob-example-com" in audits[1].filename
    calls = engine.generate_json.await_args_list
    assert len(calls) == 2
    assert "Alice spreadsheet" in calls[0].kwargs["cacheable_prompt_prefix"]
    assert "Bob career" not in calls[0].kwargs["cacheable_prompt_prefix"]
    assert "Alice spreadsheet" not in calls[1].kwargs["cacheable_prompt_prefix"]
    engine.dataset_chat_json.assert_not_awaited()
    assert "| 3 |" in result[-1].content()
    assert "Strong spreadsheet evidence." in result[-1].content()
    await module.recruiting(DATASET, "Job advert")
    assert module.generate_markdown.await_count == 1
    assert engine.generate_json.await_count == 2
    assert module.generate_json.await_count == 1
    alice.dossier = [build_chunk("New Alice evidence", "resumes/alice-smith.pdf", 1, 0)]
    engine.generate_json.return_value = assessment(4)
    await module.recruiting(DATASET, "Job advert")
    assert engine.generate_json.await_count == 3
    assert module.generate_json.await_count == 2


@pytest.mark.asyncio
async def test_manual_criteria_and_reports_are_preserved(workflow):
    module, engine, alice, _bob = workflow
    criteria = InsightFile(DATASET, "job_criteria", "manual")
    criteria.save(CRITERIA)
    manual = InsightFile(DATASET, "recruiting", "manual", identifier=alice.identifier, subdir=True)
    manual.save("Reviewed Alice assessment")
    result = await module.recruiting(DATASET, "Different job advert")
    module.generate_markdown.assert_not_awaited()
    assert result[0].path == criteria.path
    assert manual.content() == "Reviewed Alice assessment"
    assert any(item.path == manual.path for item in result)
    assert "Reviewed Alice assessment" in module.generate_json.await_args.args[0]


@pytest.mark.asyncio
async def test_criteria_change_invalidates_audit(workflow):
    module, engine, _alice, _bob = workflow
    await module.recruiting(DATASET, "Original")
    module.generate_markdown.return_value = CRITERIA.replace("pivot tables", "macros")
    await module.recruiting(DATASET, "Revised")
    assert module.generate_markdown.await_count == 2
    assert engine.generate_json.await_count == 4


@pytest.mark.asyncio
async def test_failed_audit_is_not_an_unconfirmed_score(workflow):
    module, engine, _alice, _bob = workflow
    engine.generate_json.side_effect = RuntimeError("Provider unavailable")
    with pytest.raises(RuntimeError, match="Recruiting incomplete"):
        await module.recruiting(DATASET, "Job advert")
    module.generate_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_score_is_rendered_without_inventing_zero(workflow):
    module, engine, _alice, _bob = workflow
    engine.generate_json.return_value = assessment(None)
    result = await module.recruiting(DATASET, "Job advert")
    assert "| ? |" in result[-1].content()
    assert "? = insufficient evidence to score" in result[-1].content()


@pytest.mark.asyncio
async def test_cached_profile_gathers_dossier_again(workflow, monkeypatch):
    module, _engine, alice, _bob = workflow
    alice.dossier = []
    gather = AsyncMock(return_value=(
        [build_chunk("Resume recovered", "resumes/alice-smith.pdf", 1, 0)],
        [build_chunk("Alice Smith motivation letter", "motivation.pdf", 1, 0)],
    ))
    monkeypatch.setattr(module, "build_person_dossier", gather)
    evidence = await module._evidence(DATASET, alice, load_repository_config("recruiting"))
    assert "Resume recovered" in evidence
    assert "Alice Smith motivation letter" in evidence
    assert "motivation.pdf" in evidence
    assert "Motivationsschreiben" in gather.await_args.args[2]
    gather.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_or_invalid_criteria_fail_before_discovery(workflow):
    module, _engine, _alice, _bob = workflow
    with pytest.raises(ValueError, match="Supply criteria"):
        await module.recruiting(DATASET)
    InsightFile(DATASET, "job_criteria", "manual").save("# Unexpected title\n" + CRITERIA)
    with pytest.raises(ValueError, match="exactly one"):
        await module.recruiting(DATASET)
    module.persons_in_dataset.assert_not_awaited()


def test_criteria_reviewer_rejects_h1_and_accepts_no_keywords():
    module = importlib.import_module("skills.recruiting.recruiting")
    assert not module._review_criteria(CRITERIA).problems
    assert module._review_criteria("# Title\n" + CRITERIA).problems


def test_cli_passes_file_contents_and_rejects_conflicting_inputs(tmp_path, monkeypatch):
    module = importlib.import_module("skills.recruiting.__main__")
    job = tmp_path / "job.md"
    job.write_text("Actual job advert")
    run = AsyncMock(return_value=[])
    monkeypatch.setattr(module, "recruiting", run)
    result = CliRunner().invoke(module.app, ["--dataset", DATASET, "--criteria-file", str(job)])
    assert result.exit_code == 0, result.output
    run.assert_awaited_once_with(DATASET, "Actual job advert")
    result = CliRunner().invoke(module.app, [
        "--dataset", DATASET, "--criteria", "text", "--criteria-file", str(job),
    ])
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_harness_passes_criteria_file(tmp_path, monkeypatch):
    module = importlib.import_module("skills.harness.harness")
    package = importlib.import_module("skills.recruiting")
    run = AsyncMock(return_value=[])
    monkeypatch.setattr(package, "recruiting", run)
    job = tmp_path / "job.md"
    job.write_text("Job description")
    await module._recruiting([DATASET, "--criteria-file", str(job)])
    run.assert_awaited_once_with(DATASET, "Job description")


@pytest.mark.asyncio
async def test_fresh_profile_mentions_reach_audit_with_source_metadata(workflow):
    module, engine, alice, _bob = workflow
    alice.mentions = [
        build_chunk("Alice Smith explains her motivation", "motivation.pdf", 2, 0)
    ]
    await module.recruiting(DATASET, "Job advert")
    prefix = engine.generate_json.await_args_list[0].kwargs["cacheable_prompt_prefix"]
    assert "Alice Smith explains her motivation" in prefix
    assert alice.mentions[0].to_md() in prefix
    assert "Alice spreadsheet experience" in prefix
    assert "LinkedIn profile:" in prefix
    assert "Persuasive writing" in prefix


@pytest.mark.asyncio
async def test_changed_motivation_invalidates_applicant_audit(workflow):
    module, engine, alice, _bob = workflow
    alice.mentions = [build_chunk("First motivation", "motivation.pdf", 1, 0)]
    await module.recruiting(DATASET, "Job advert")
    alice.mentions = [build_chunk("Revised motivation", "motivation.pdf", 1, 0)]
    await module.recruiting(DATASET, "Job advert")
    assert engine.generate_json.await_count == 3


def test_overview_schema_uses_config_without_mutating_it(mock_env):
    module = importlib.import_module("skills.recruiting.recruiting")
    template = load_repository_config("recruiting", "overview_response_schema")
    before = json.dumps(template, sort_keys=True)
    schema = module._overview_schema(["alice"], template)
    assert schema["properties"]["alice"] == template["additionalProperties"]
    assert schema["required"] == ["alice"]
    assert schema["additionalProperties"] is False
    assert json.dumps(template, sort_keys=True) == before


@pytest.mark.asyncio
async def test_overview_displays_configured_score_bounds(workflow, monkeypatch):
    module, _engine, _alice, _bob = workflow
    config = load_repository_config("recruiting")
    config["audit_response_schema"]["properties"]["score"]["maximum"] = 7
    monkeypatch.setattr(module, "load_repository_config", lambda *_: config)
    result = await module.recruiting(DATASET, "Job advert")
    assert "Scores: 1–7" in result[-1].content()


def test_recruiting_schema_preserves_local_status_checks_without_provider_allof(mock_env):
    from lib.infrastructure.ai_text_generation.json import (
        json_schema_response_format, validate_json_schema,
    )
    schema = load_repository_config("recruiting", "audit_response_schema")
    provider = json_schema_response_format(schema)["json_schema"]["schema"]
    assert "allOf" not in provider
    assert "if" not in provider
    validate_json_schema(assessment(3), schema)
    validate_json_schema(assessment(None), schema)
    contradictory = {**assessment(3), "status": "unconfirmed"}
    with pytest.raises(ValueError):
        validate_json_schema(contradictory, schema)


@pytest.mark.asyncio
async def test_overview_sends_audit_once_and_only_manual_reports(workflow):
    module, _engine, alice, _bob = workflow
    manual = InsightFile(DATASET, "recruiting", "manual", identifier=alice.identifier, subdir=True)
    manual.save("Committee correction")
    await module.recruiting(DATASET, "Job advert")
    prompt = module.generate_json.await_args.args[0]
    payload = json.loads(prompt.split("\n\nAssessments:\n", 1)[1])
    assert payload[0]["report"] == "Committee correction"
    assert "report" not in payload[1]
    assert all(len(record["assessments"]) == 1 for record in payload)


@pytest.mark.asyncio
async def test_evidence_always_gathers_and_preserves_both_kinds(workflow, monkeypatch):
    module, _engine, alice, _bob = workflow
    alice.mentions = [build_chunk("Existing mention", "letter.pdf", 1, 0)]
    new_mention = build_chunk("New motivation detail", "letter.pdf", 2, 0)
    gather = AsyncMock(return_value=(alice.dossier, [*alice.mentions, new_mention]))
    monkeypatch.setattr(module, "build_person_dossier", gather)
    evidence = await module._evidence(DATASET, alice, load_repository_config("recruiting"))
    gather.assert_awaited_once()
    assert evidence.count("Alice spreadsheet experience") == 1
    assert evidence.count("Existing mention") == 1
    assert new_mention.to_md() in evidence


@pytest.mark.parametrize("score", [0, 7])
def test_recruiting_rejects_scores_outside_one_to_six(mock_env, score):
    from lib.infrastructure.ai_text_generation.json import validate_json_schema
    schema = load_repository_config("recruiting", "audit_response_schema")
    with pytest.raises(ValueError):
        validate_json_schema(assessment(score), schema)


@pytest.mark.asyncio
async def test_overview_includes_schema_score_legend(workflow):
    module, _engine, _alice, _bob = workflow
    result = await module.recruiting(DATASET, "Job advert")
    text = result[-1].content()
    assert "Scores: 1–6" in text
    for value, label in [(1, "does not meet"), (2, "limited fit"), (3, "partial fit"),
                         (4, "meets"), (5, "exceeds"), (6, "overqualified")]:
        assert f"{value} = {label}" in text


@pytest.mark.asyncio
async def test_overview_ranks_all_candidates_with_criteria_and_person_context(workflow):
    module, _engine, alice, bob = workflow
    result = await module.recruiting(DATASET, "Job advert")
    call = module.generate_json.await_args
    prompt = call.args[0]
    assert CRITERIA in prompt
    payload = json.loads(prompt.split("\n\nAssessments:\n", 1)[1])
    assert payload[0]["person"]["person_profile_markdown"] == "Alice profile"
    assert payload[0]["person"]["linkedin_profile"] == alice.linkedin_profile
    assert alice.dossier[0].to_md() in payload[0]["person"]["dossier"]
    assert payload[0]["assessments"][0]["result"]["rationale"] == "Relevant experience"
    text = result[-1].content()
    assert "| Rank | Full name |" in text
    assert text.index("[Bob Jones]") < text.index("[Alice Smith]")
    assert "| 1 | [Bob Jones]" in text
    assert "| 2 | [Alice Smith]" in text
    assert call.kwargs["reviewer"] is module._review_ranks


@pytest.mark.parametrize("ranks", [[1, 1], [1, 3], [0, 1]])
def test_overview_reviewer_rejects_invalid_ranks(ranks):
    module = importlib.import_module("skills.recruiting.recruiting")
    output = {name: {"rank": rank, "rationale": "Fit"}
              for name, rank in zip(["alice", "bob"], ranks)}
    assert module._review_ranks(output).problems


def test_overview_reviewer_accepts_complete_ranks():
    module = importlib.import_module("skills.recruiting.recruiting")
    output = {"alice": {"rank": 2}, "bob": {"rank": 1}}
    assert not module._review_ranks(output).problems


@pytest.mark.asyncio
async def test_overqualified_score_is_accepted_and_rendered(workflow):
    from lib.infrastructure.ai_text_generation.json import validate_json_schema
    module, engine, _alice, _bob = workflow
    schema = load_repository_config("recruiting", "audit_response_schema")
    validate_json_schema(assessment(6), schema)
    engine.generate_json.return_value = assessment(6)
    result = await module.recruiting(DATASET, "Job advert")
    assert "| 6 |" in result[-1].content()
    assert "6 = overqualified" in result[-1].content()
