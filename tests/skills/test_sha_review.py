from __future__ import annotations

import asyncio
import json
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import load_repository_config
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
@pytest.mark.parametrize(
    ("selected_path", "resolves"),
    [
        ("legal/latest-sha.pdf", True),
        ("legal/latest-sha.pdff", True),
        ("unresolvable-zzzzzzzzzzzzzzzz.txt", False),
    ],
)
async def test_sha_path_resolution_preserves_llm_selection(
    mock_env, monkeypatch, selected_path, resolves,
):
    module = importlib.import_module("skills.sha_review.sha_review")
    _create_startup_dataset("acme")
    location = dataset_location_for_domain("acme", "startups")
    get_storage().write_text(
        f"{location.parsed_rel}/legal/latest-sha.pdf.md",
        "# Latest selected agreement",
    )
    get_storage().write_text(
        f"{location.parsed_rel}/legal/older-sha.pdf.md",
        "# Older alternative agreement",
    )
    identification = {
        "path": selected_path,
        "document_match": "Medium",
        "concerns": ["The selected agreement's execution date is uncertain."],
        "paths_for_alternative_candidates": ["legal/older-sha.pdf"],
        "selection_reason": "The selected agreement is substantively preferred.",
    }

    async def identify(**kwargs):
        return identification

    monkeypatch.setattr(module, "dataset_chat_json", identify)
    config = load_repository_config("sha_review")
    if not resolves:
        with pytest.raises(ValueError, match="Could not resolve"):
            await module._identify_sha("acme", config)
        return

    path, markdown, metadata = await module._identify_sha("acme", config)
    assert path == "legal/latest-sha.pdf.md"
    assert markdown == "# Latest selected agreement"
    assert metadata == identification


@pytest.mark.asyncio
async def test_sha_checks_assess_full_agreement_without_search_hits(
    mock_env, monkeypatch,
):
    module = importlib.import_module("skills.sha_review.sha_review")
    chat = importlib.import_module("skills.dataset_chat.dataset_chat")
    _create_startup_dataset("acme")
    calls = []

    async def no_hits(*args, **kwargs):
        return []

    async def assess(prompt, schema, reviewer, *, cacheable_prompt_prefix):
        calls.append(prompt)
        assert "Clause 8: investors appoint one director." in cacheable_prompt_prefix
        assert "Reference clause 9: investors appoint one director." in cacheable_prompt_prefix
        return {
            "status": "balanced",
            "rationale": "Clause 8 follows the reference's single investor seat.",
            "source_documents": ["legal/sha.pdf — clause 8"],
            "proposed_next_steps_and_questions": [],
        }

    monkeypatch.setattr(chat, "dataset_search", no_hits)
    monkeypatch.setattr(chat, "generate_json", assess)
    config = load_repository_config("sha_review")
    config["checklists"] = {
        "board": "# Board\n\n## Appointment\n\n### Investor seat\n\n"
        "Are the investor board appointment rights balanced?\n",
    }
    config["reference_shas"] = {
        "reference": "Reference clause 9: investors appoint one director.",
    }
    audits = await module._run_audits(
        "acme", "legal/sha.pdf", "Clause 8: investors appoint one director.",
        "reference", config,
    )
    [check] = audits[0][1]["chapters"][0]["checks"]
    assert len(calls) == 1
    assert check["status"] == "balanced"
    assert check["source_documents"] == ["legal/sha.pdf — clause 8"]
    assert check["error"] is None


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
            "REFERENCE:\n{{reference_sha}}"
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
        "load_repository_config",
            lambda: {
                "sha_review": sha_config,
                "batch_audit": {"response_schema": {}, "llm_instructions": ""},
                "structured_output": {
                    "json_response_instructions": "fixture"
                },
            },
    )

    async def fake_sync(*_args, **_kwargs):
        return []

    async def fake_ensure_startup_dataset(startup):
        return SimpleNamespace(dataset_slug=startup.lower())

    identification_prompts = []

    async def fake_dataset_chat_json(*_args, **kwargs):
        identification_prompts.append(kwargs["prompt"])
        return {
            "path": "legal/shareholders-agrement.pdf",
            "document_match": "Medium",
            "concerns": [
                "No signature page was found in the retrieved text.",
                "The agreement date could not be verified internally.",
            ],
            "paths_for_alternative_candidates": [],
            "selection_reason": "Operative provisions substantively match a SHA.",
        }

    json_calls = []

    async def fake_generate_json(prompt, schema, reviewer):
        json_calls.append((prompt, schema, reviewer))
        return {
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

    async def fake_generate_markdown(prompt):
        return "## 1. Material finding\n\nAutomated review summary."

    audit_calls = []
    audit_starts = []

    async def fake_batch_audit(**kwargs):
        audit_calls.append(kwargs)
        title = "Review Two" if "Review Two" in kwargs["checklist_markdown"] else "Review"
        audit_starts.append(title)
        await asyncio.sleep(0)
        assert len(audit_starts) == 2
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
        return SimpleNamespace(content=lambda: json.dumps(audit))

    monkeypatch.setattr(module, "sync_datasets", fake_sync)
    monkeypatch.setattr(
        module,
        "ensure_startup_dataset",
        fake_ensure_startup_dataset,
    )
    monkeypatch.setattr(module, "dataset_chat_json", fake_dataset_chat_json)
    monkeypatch.setattr(module, "generate_json", fake_generate_json)
    monkeypatch.setattr(module, "generate_markdown", fake_generate_markdown)
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
    assert len(identification_prompts) == 1
    assert len(json_calls) == 1
    assert json_calls[0][2]({"rankings": []}).problems


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
    response = {
        "path": path,
        "document_match": document_match,
        "concerns": [],
        "paths_for_alternative_candidates": [],
        "selection_reason": "Fixture selection rationale.",
    }

    with pytest.raises(ValueError, match="null path if and only if"):
        module._parse_identification(response)


def test_sha_identification_stops_only_when_no_candidate_exists(mock_env):
    module = importlib.import_module("skills.sha_review.sha_review")
    response = {
        "path": None,
        "document_match": "None",
        "concerns": ["No substantive SHA candidate was retrieved."],
        "paths_for_alternative_candidates": [],
        "selection_reason": "The retrieved documents do not contain SHA terms.",
    }

    with pytest.raises(
        ValueError,
        match="No plausible Shareholders' Agreement could be identified",
    ):
        module._parse_identification(response)
