import asyncio
import json

import pytest
from pathlib import Path
from types import SimpleNamespace

from lib.batch_audit import batch_audit
from lib.batch_audit.checklist import parse_checklist
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import load_repository_config
from lib.storage import get_storage
from skills.dd_checks.dd_checks import (
    chapter_by_chapter,
    find_industry_type,
    parse_industry_type,
)

AUDIT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "config/dd_checks/audit_response_schema.json").read_text()
)


INDUSTRY_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "config/dd_checks/industry_type_response_schema.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.asyncio
async def test_public_batch_audit_returns_json_insight(mock_env, monkeypatch):
    get_storage().mkdir(
        dataset_location_for_domain("example-startup", "startups").raw_rel
    )

    async def fake_dataset_chat(**_kwargs):
        return {
            "status": "Fine",
            "rationale": "Evidence found",
            "source_documents": ["Pitch Deck — page 1"],
            "proposed_next_steps_and_questions": [],
        }

    monkeypatch.setattr(
        "lib.batch_audit.engine.llm_model",
        lambda: "google/gemini-2.5-pro",
    )
    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        fake_dataset_chat,
    )

    insight = await batch_audit(
        "example-startup",
        """# Commercial

## Traction

### Customer traction

Is there evidence of customer traction?

**Keywords:** customers, revenue
""",
        skill_name="dd_checks",
        llm_instructions="Return JSON.",
        response_schema=AUDIT_SCHEMA,
    )

    audit = json.loads(insight.content())
    assert insight.filename == "dd-checks-commercial-gemini-2-5-pro.json"
    assert insight.directory.endswith("/insights/batch-audit")
    assert audit["chapters"][0]["checks"][0]["result"]["status"] == "Fine"


def test_parse_industry_type_validates_structured_response():
    response = json.dumps(
        {
            "industry_type": "software",
            "confidence": 95,
            "evidence": ["The product is delivered as SaaS."],
        }
    )

    result = parse_industry_type(
        response,
        {"biology", "hardware", "software", "general"},
        INDUSTRY_SCHEMA,
    )

    assert result == "software"


def test_parse_industry_type_defaults_to_general_for_null_classification():
    result = parse_industry_type(
        json.dumps(
            {"industry_type": None, "confidence": 0, "evidence": []}
        ),
        {"biology", "hardware", "software", "general"},
        INDUSTRY_SCHEMA,
    )

    assert result == "general"


@pytest.mark.asyncio
async def test_find_industry_type_uses_default_retrieval_chunk_count(monkeypatch):
    calls = {}

    async def fake_dataset_chat(*args, **kwargs):
        calls["kwargs"] = kwargs
        return {
            "industry_type": "hardware",
            "confidence": 95,
            "evidence": ["The company manufactures a device."],
        }

    monkeypatch.setattr(
        "skills.dd_checks.dd_checks.dataset_chat_json",
        fake_dataset_chat,
    )

    result = await find_industry_type(
        "proud-technology",
        {
            "industry_type_query": "classify the startup",
            "industry_type_llm_instructions": "choose one industry type",
            "industry_type_response_schema": INDUSTRY_SCHEMA,
        },
        {"biology", "general", "hardware", "software"},
    )

    assert result == "hardware"
    assert "max_chunks" not in calls["kwargs"]
    schema = calls["kwargs"]["schema"]
    assert schema["properties"]["industry_type"]["enum"] == [
        "biology",
        "general",
        "hardware",
        "software",
        None,
    ]


@pytest.mark.asyncio
async def test_find_industry_type_supplies_business_reviewer(monkeypatch):
    reviews = []

    async def fake_dataset_chat(*_args, **kwargs):
        reviewer = kwargs["reviewer"]
        reviews.append(
            reviewer(
                {
                    "industry_type": "hardware",
                    "confidence": 50,
                    "evidence": [],
                }
            )
        )
        return {
            "industry_type": "software",
            "confidence": 95,
            "evidence": ["The product is delivered as SaaS."],
        }

    monkeypatch.setattr(
        "skills.dd_checks.dd_checks.dataset_chat_json",
        fake_dataset_chat,
    )

    result = await find_industry_type(
        "example-startup",
        {
            "industry_type_query": "classify the startup",
            "industry_type_llm_instructions": "choose one industry type",
            "industry_type_response_schema": INDUSTRY_SCHEMA,
        },
        {"general", "hardware", "software"},
    )

    assert result == "software"
    assert reviews[0].problems == (
        "Industry classification requires evidence when a type is selected.",
    )


@pytest.mark.asyncio
async def test_dd_chapters_submit_audits_concurrently_in_output_order(
    monkeypatch,
):
    from skills.dd_checks import dd_checks as module

    started = []
    all_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_batch_audit(**kwargs):
        checklist = kwargs["checklist_markdown"]
        started.append(checklist)
        if len(started) == 2:
            all_started.set()
        await release.wait()
        return type("Audit", (), {"content": lambda self: checklist})()

    monkeypatch.setattr(module, "batch_audit", fake_batch_audit)
    monkeypatch.setattr(module, "validate_audit_document", lambda _value, **_kwargs: {})
    monkeypatch.setattr(
        module,
        "json_to_markdown_table",
        lambda insight: insight.content(),
    )

    task = asyncio.create_task(
        chapter_by_chapter(
            "example-startup",
            ["commercial", "legal"],
            "software",
            {
                "audit_response_schema": AUDIT_SCHEMA,
                "checklists": {
                    "commercial_general": '"commercial checklist"',
                    "legal_software": '"legal checklist"',
                }
            },
            "Shared audit instructions",
        )
    )

    await asyncio.wait_for(all_started.wait(), timeout=1)
    assert started == ['"commercial checklist"', '"legal checklist"']
    release.set()

    sections = await task
    assert sections == [
        '## Chapter: commercial\n\n"commercial checklist"\n',
        '## Chapter: legal\n\n"legal checklist"\n',
    ]


@pytest.mark.asyncio
async def test_find_industry_type_preserves_missing_evidence_fallback(
    monkeypatch,
):
    calls = 0

    async def fake_dataset_chat(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(
        "skills.dd_checks.dd_checks.dataset_chat_json",
        fake_dataset_chat,
    )

    result = await find_industry_type(
        "example-startup",
        {
            "industry_type_query": "classify the startup",
            "industry_type_llm_instructions": "choose one industry type",
            "industry_type_response_schema": INDUSTRY_SCHEMA,
        },
        {"general", "hardware", "software"},
    )

    assert result == "general"
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("industry", ["general", "biology", "hardware", "software"])
async def test_configured_dd_product_fallback_preserves_specialist_selection(
    mock_env, monkeypatch, industry,
):
    from skills.dd_checks import dd_checks as module

    config = load_repository_config("dd_checks")
    chapters = sorted({key.rsplit("_", 1)[0] for key in config["checklists"]})
    selected = []

    async def audit(**kwargs):
        selected.append(parse_checklist(kwargs["checklist_markdown"]))
        return SimpleNamespace(content=lambda: "{}")

    monkeypatch.setattr(module, "batch_audit", audit)
    monkeypatch.setattr(module, "validate_audit_document", lambda value, **_kwargs: value)
    monkeypatch.setattr(module, "json_to_markdown_table", lambda insight: "table")
    sections = await chapter_by_chapter(
        "example-startup", chapters, industry, config, "Audit instructions",
    )

    assert len(sections) == len(selected) == 7
    product = selected[-1]
    expected = parse_checklist(config["checklists"][f"7_product_{industry}"])
    assert product == expected
    assert all(check.number.startswith("7.") for chapter in product.chapters for check in chapter.checks)
    assert "## Chapter: 7_product" in sections[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [None, 'revision', 'config', 'manual'])
async def test_dd_final_report_reuse_precedes_classification(mock_env, monkeypatch, change):
    from copy import deepcopy
    from unittest.mock import AsyncMock
    from lib.datasets.manifest import IngestionManifest
    from lib.insights import InsightFile
    from skills.dd_checks import dd_checks as module

    storage = get_storage()
    location = dataset_location_for_domain('example-startup', 'startups')
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = 'revision-1'
    manifest.save()
    model = 'ollama/test-model:1b'
    monkeypatch.setenv('RANKED_LLMS', model)
    monkeypatch.setattr(module, 'llm_model', lambda: model)
    prepare = AsyncMock(return_value=SimpleNamespace(dataset_slug='example-startup'))
    monkeypatch.setattr('lib.startups.sources.ensure_startup_dataset', prepare)
    sync = AsyncMock()
    monkeypatch.setattr(module, 'sync_datasets', sync)
    classify = AsyncMock(return_value='general')
    chapters = AsyncMock(return_value=['## Chapter\nAccepted assessment.'])
    monkeypatch.setattr(module, 'find_industry_type', classify)
    monkeypatch.setattr(module, 'chapter_by_chapter', chapters)

    [first] = await module.dd_checks('example-startup')
    classify.reset_mock()
    chapters.reset_mock()
    if change == 'revision':
        async def update_revision(*args, **kwargs):
            manifest.indexed_dataset_revision = 'revision-2'
            manifest.save()
        sync.side_effect = update_revision
    elif change == 'config':
        config = deepcopy(load_repository_config())
        config['dd_checks']['audit_instructions'] += '\nChanged assessment guidance.'
        monkeypatch.setattr(module, 'load_repository_config', lambda: config)
    elif change == 'manual':
        manual = InsightFile('example-startup', 'dd_checks', 'manual')
        manual.save('# Reviewed DD report')

    [second] = await module.dd_checks('example-startup')
    assert sync.await_count == 2
    if change in {'revision', 'config'}:
        classify.assert_awaited_once()
        chapters.assert_awaited_once()
    else:
        classify.assert_not_awaited()
        chapters.assert_not_awaited()
        assert second.path == (manual.path if change == 'manual' else first.path)
        assert second.content() == ('# Reviewed DD report' if change == 'manual' else first.content())
