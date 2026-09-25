import json
from pathlib import Path

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.jury_priorities.jury_priorities import (
    SECTION_ORDER,
    _parse_sections,
    _render_sections,
    _review_report,
    _validate_report_evidence,
    jury_priorities,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "config" / "jury_priorities" / "response_schema.json"
SOURCE_REPORT = (
    "# Synthetic saved rating report\n\n"
    "| Check | Status | Evidence |\n|---|---|---|\n"
    "| synthetic-check | Found | Synthetic evidence excerpt |\n"
)


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _sections(**overrides) -> list[dict]:
    sections = []
    for name in SECTION_ORDER:
        sections.append(
            {
                "name": name,
                "summary": f"Synthetic summary for {name}.",
                "jury_questions": [f"Synthetic question for {name}?"],
                "evidence": ["Synthetic evidence excerpt"],
            }
        )
    for index, section in enumerate(sections):
        section.update(overrides.get(section["name"], {}))
        sections[index] = section
    return sections


def _create_startup_dataset(name: str) -> None:
    location = dataset_location_for_domain(name, "startups")
    get_storage().mkdir(location.raw_rel)


def test_focused_tests_import_the_local_public_package():
    import skills.jury_priorities.jury_priorities as module

    assert Path(module.__file__).resolve().is_relative_to(REPO_ROOT)


def test_schema_is_non_ratable_and_questions_are_optional():
    properties = _schema()["properties"]["sections"]["items"]["properties"]
    assert "rating" not in properties
    assert "classification" not in properties

    sections = _sections(Team={"jury_questions": []})
    parsed = _parse_sections(json.dumps({"sections": sections}), _schema())
    assert parsed[0]["jury_questions"] == []


def test_missing_section_is_rejected():
    with pytest.raises(ValueError):
        _parse_sections(json.dumps({"sections": _sections()[:3]}), _schema())


def test_unknown_section_is_rejected():
    sections = _sections()
    sections[0]["name"] = "Synthetic section"
    with pytest.raises(ValueError):
        _parse_sections(json.dumps({"sections": sections}), _schema())


def test_rendering_has_no_generated_rating_field_and_keeps_order():
    rendered = _render_sections(_sections(Team={"jury_questions": []}))
    positions = [rendered.index(f"## {name}") for name in SECTION_ORDER]
    assert positions == sorted(positions)
    assert "**Rating:**" not in rendered
    assert "None identified in the saved report." in rendered


def test_evidence_must_be_nonempty_and_present_in_report():
    sections = _sections(Team={"evidence": ["synthetic text absent from report"]})
    with pytest.raises(ValueError, match="not present"):
        _validate_report_evidence(sections, SOURCE_REPORT)

    review = _review_report({"sections": sections}, SOURCE_REPORT)
    assert review.problems


@pytest.mark.asyncio
async def test_synthesizes_only_an_existing_saved_report(mock_env, monkeypatch):
    _create_startup_dataset("synthetic-startup")
    InsightFile("synthetic-startup", "jury_rating", "manual").save(SOURCE_REPORT)
    prompts = []

    async def fake_generate_json(prompt, schema, reviewer=None, **kwargs):
        prompts.append((prompt, schema, kwargs))
        assert "rating" not in schema["properties"]["sections"]["items"]["properties"]
        result = {"sections": _sections(Team={"jury_questions": []})}
        assert reviewer is not None
        reviewed = reviewer(result)
        assert reviewed.accepted
        return reviewed.output

    monkeypatch.setattr(
        "skills.jury_priorities.jury_priorities.generate_json",
        fake_generate_json,
    )

    [insight] = await jury_priorities("Synthetic Startup")

    assert insight.path.startswith("storage/startups/synthetic-startup/insights/jury-priorities-")
    assert SOURCE_REPORT in prompts[0][0]
    output = get_storage().read_text(insight.path)
    assert "Jury briefing: Synthetic Startup" in output
    assert "**Rating:**" not in output
    assert "None identified in the saved report." in output


@pytest.mark.asyncio
async def test_requires_existing_saved_rating_report(mock_env):
    with pytest.raises(ValueError, match="Create a jury_rating report"):
        await jury_priorities("missing-startup")


@pytest.mark.asyncio
async def test_rejects_empty_saved_rating_report(mock_env):
    _create_startup_dataset("synthetic-startup")
    InsightFile("synthetic-startup", "jury_rating", "manual").save("")

    with pytest.raises(ValueError, match="report for 'synthetic-startup' is empty"):
        await jury_priorities("synthetic-startup")
