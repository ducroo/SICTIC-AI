from __future__ import annotations

import json
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage


def _actual_identification_schema() -> dict:
    return json.loads(
        Path(
            "config/sha_review/document_identification_response_schema.json"
        ).read_text(encoding="utf-8")
    )


def _create_startup_dataset(name: str) -> None:
    location = dataset_location_for_domain(name, "startups")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.parsed_rel)
    storage.mkdir(location.insights_rel)


@pytest.mark.asyncio
async def test_sha_review_composes_existing_skills_and_returns_summary(
    mock_env,
    monkeypatch,
):
    module = importlib.import_module("skills.sha_review.sha_review")

    _create_startup_dataset("acme")
    location = dataset_location_for_domain("acme", "startups")
    get_storage().write_text(
        f"{location.parsed_rel}/legal/shareholders-agreement.pdf.md",
        "# Shareholders Agreement\n\nSigned on 1 January 2025.",
    )

    identification_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {"type": ["string", "null"]},
            "document_match": {
                "type": "string",
                "enum": ["High", "Medium", "Low", "None"],
            },
            "concerns": {
                "type": "array",
                "items": {"type": "string"},
            },
            "paths_for_alternative_candidates": {
                "type": "array",
                "items": {"type": "string"},
            },
            "selection_reason": {"type": "string"},
        },
        "required": [
            "path",
            "document_match",
            "concerns",
            "paths_for_alternative_candidates",
            "selection_reason",
        ],
    }
    ranking_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "rankings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "template_key": {"type": "string"},
                        "rationale_for_rank": {"type": "string"},
                    },
                    "required": ["template_key", "rationale_for_rank"],
                },
            },
        },
        "required": ["rankings"],
    }
    checklist = (
        "# Review\n\n## Terms\n\n### Balance\n\n"
        "Is the provision balanced?\n"
    )
    status_scale = ["unclear", "too weak", "balanced", "too strong"]
    sha_config = {
        "document_identification_queries": ["signed shareholders agreement"],
        "document_identification_prompt": "Find the latest signed SHA.",
        "document_identification_response_schema": identification_schema,
        "document_identification_settings": {
            "max_chunks": 25,
        },
        "document_path_resolution": {"min_score": 78},
        "reference_shas": {
            "large": "# Large reference SHA",
            "light": "# Light reference SHA",
        },
        "template_ranking_prompt": "Rank every template.",
        "template_ranking_response_schema": ranking_schema,
        "audit_instructions": (
            "SHA:\n{{sha_under_review}}\n\n"
            "REFERENCE:\n{{reference_sha}}\n\n"
            "SCHEMA:\n{{response_schema}}"
        ),
        "checklists": {
            "first": checklist,
            "second": checklist.replace("# Review", "# Review Two"),
        },
        "audit_settings": {
            "status_scale": status_scale,
            "missing_evidence_status": "unclear",
        },
        "summary_instructions": "Summarize {{startup}}.",
    }
    monkeypatch.setattr(
        module,
        "config_load",
        lambda: {
            "sha_review": sha_config,
            "batch_audit": {"response_schema": {}, "llm_instructions": ""},
        },
    )

    async def fake_sync(*_args, **_kwargs):
        return []

    async def fake_ensure_startup_dataset(startup):
        return SimpleNamespace(dataset_slug=startup.lower())

    async def fake_dataset_chat(*_args, **_kwargs):
        return json.dumps(
            {
                "path": "legal/shareholders-agrement.pdf",
                "document_match": "Medium",
                "concerns": [
                    "No signature page was found in the retrieved text.",
                    "The agreement date could not be verified internally.",
                ],
                "paths_for_alternative_candidates": [],
                "selection_reason": "Operative provisions substantively match a SHA.",
            }
        )

    llm_calls = []

    async def fake_llm_chat(*, prompt, response_format=None):
        llm_calls.append((prompt, response_format))
        if response_format is not None:
            return json.dumps(
                {
                    "rankings": [
                        {
                            "template_key": "light",
                            "rationale_for_rank": "Closest overall structure.",
                        },
                        {
                            "template_key": "large",
                            "rationale_for_rank": "More complex than the SHA.",
                        },
                    ]
                }
            )
        return "## 1. Material finding\n\nAutomated review summary."

    audit_calls = []

    async def fake_batch_audit(**kwargs):
        audit_calls.append(kwargs)
        title = "Review Two" if "Review Two" in kwargs["checklist_markdown"] else "Review"
        audit = {
            "schema_version": 1,
            "skill": "sha_review",
            "checklist_title": title,
            "dataset": "acme",
            "model": "ollama/test_model:1b",
            "generated_at": "2026-08-20T00:00:00Z",
            "status_scale": status_scale,
            "chapters": [
                {
                    "number": "1",
                    "title": "Terms",
                    "checks": [
                        {
                            "number": "1.1",
                            "check": "Balance",
                            "status": "balanced",
                            "rationale": "Fixture rationale.",
                            "source_documents": [
                                "legal/shareholders-agreement.pdf"
                            ],
                            "proposed_next_steps_and_questions": [],
                            "error": None,
                        }
                    ],
                }
            ],
        }
        return [SimpleNamespace(content=lambda: json.dumps(audit))]

    monkeypatch.setattr(module, "sync_datasets", fake_sync)
    monkeypatch.setattr(
        module,
        "ensure_startup_dataset",
        fake_ensure_startup_dataset,
    )
    monkeypatch.setattr(module, "dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(module, "llm_chat", fake_llm_chat)
    monkeypatch.setattr(module, "batch_audit", fake_batch_audit)

    result = await module.sha_review("ACME")

    assert len(result) == 1
    assert isinstance(result[0], InsightFile)
    report = result[0].content()
    assert report.startswith("# Shareholders' Agreement Review\n\n")
    assert (
        "- **Shareholders' Agreement:** "
        "`legal/shareholders-agreement.pdf.md`" in report
    )
    assert "- **Document match:** Medium" in report
    assert "- **Closest reference template:** `light`" in report
    assert "## Document-selection concerns" in report
    assert "- No signature page was found in the retrieved text." in report
    assert "- The agreement date could not be verified internally." in report
    assert report.index("## Document-selection concerns") < report.index(
        "Material finding"
    )
    assert "Operative provisions substantively match a SHA." not in report
    assert "Material finding" in report
    assert len(audit_calls) == 2
    assert all(call["status_scale"] == status_scale for call in audit_calls)
    assert all(call["missing_evidence_status"] == "unclear" for call in audit_calls)
    assert "legal/shareholders-agreement.pdf.md" in audit_calls[0]["llm_instructions"]
    assert len(llm_calls) == 2
    assert llm_calls[0][1] is not None
    assert llm_calls[1][1] is None


@pytest.mark.parametrize(
    ("path", "document_match"),
    [
        (None, "Medium"),
        ("legal/shareholders-agreement.pdf", "None"),
    ],
)
def test_sha_identification_rejects_inconsistent_none_result(
    mock_env,
    path,
    document_match,
):
    module = importlib.import_module("skills.sha_review.sha_review")
    response = json.dumps(
        {
            "path": path,
            "document_match": document_match,
            "concerns": [],
            "paths_for_alternative_candidates": [],
            "selection_reason": "Fixture selection rationale.",
        }
    )

    with pytest.raises(ValueError, match="null path if and only if"):
        module._parse_identification(response, _actual_identification_schema())


def test_sha_identification_stops_only_when_no_candidate_exists(mock_env):
    module = importlib.import_module("skills.sha_review.sha_review")
    response = json.dumps(
        {
            "path": None,
            "document_match": "None",
            "concerns": ["No substantive SHA candidate was retrieved."],
            "paths_for_alternative_candidates": [],
            "selection_reason": "The retrieved documents do not contain SHA terms.",
        }
    )

    with pytest.raises(
        ValueError,
        match="No plausible Shareholders' Agreement could be identified",
    ):
        module._parse_identification(response, _actual_identification_schema())
