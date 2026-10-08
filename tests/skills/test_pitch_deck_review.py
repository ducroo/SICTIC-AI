import importlib
import json

import pytest

from lib.batch_audit.checklist import parse_checklist
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import load_repository_config
from lib.storage import get_storage


def test_pitch_deck_checklist_covers_published_criteria():
    checklist = parse_checklist(load_repository_config("pitch_deck_review", "checklist"))

    titles = [chapter.title for chapter in checklist.chapters]
    assert titles == [
        "Business potential",
        "Product innovation",
        "Team potential",
        "Document quality",
        "Investment criteria",
    ]
    names = [check.name for chapter in checklist.chapters for check in chapter.checks]
    assert "Valuation cap" in names
    assert "Round size" in names
    assert "More than one founder" in names
    assert all(check.description for check in (
        check for chapter in checklist.chapters for check in chapter.checks
    ))


@pytest.mark.asyncio
async def test_pitch_deck_review_saves_a_report(mock_env, monkeypatch):
    get_storage().mkdir(dataset_location_for_domain("acme", "startups").raw_rel)

    async def fake_sync(*_args, **_kwargs):
        return []

    async def fake_chat(**_kwargs):
        return {
            "status": "Fine",
            "rationale": "The deck states this.",
            "source_documents": ["deck.pdf page 2"],
            "proposed_next_steps_and_questions": [],
        }

    module = importlib.import_module("skills.pitch_deck_review.pitch_deck_review")
    monkeypatch.setattr(module, "sync_datasets", fake_sync)
    monkeypatch.setattr("lib.batch_audit.engine.dataset_chat_json", fake_chat)
    monkeypatch.setattr("lib.batch_audit.engine.llm_model", lambda: "ollama/test_model:1b")

    from skills.pitch_deck_review.pitch_deck_review import pitch_deck_review

    [insight] = await pitch_deck_review("acme")
    report = insight.content()

    assert insight.skill == "pitch_deck_review"
    assert "Pitch deck review" in report
    assert "Valuation cap" in report
    assert "| Fine |" in report
    audit_files = get_storage().list(
        "storage/startups/acme/insights/batch-audit", suffix=".json"
    )
    assert audit_files
    audit = json.loads(
        get_storage().read_text(
            f"storage/startups/acme/insights/batch-audit/{audit_files[0]}"
        )
    )
    assert audit["chapters"][0]["checks"][0]["result"]["status"] == "Fine"


@pytest.mark.asyncio
async def test_pitch_deck_review_requires_a_dataset(mock_env):
    from skills.pitch_deck_review.pitch_deck_review import pitch_deck_review

    with pytest.raises(FileNotFoundError, match="missing-deck"):
        await pitch_deck_review("missing-deck")
