import json

import pytest
from pathlib import Path

from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from skills.batch_audit.batch_audit import batch_audit
from skills.dd_checks.dd_checks import find_industry_type, parse_industry_type


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
        return json.dumps(
            {
                "status": "Fine",
                "rationale": "Evidence found",
                "source_documents": ["Pitch Deck — page 1"],
                "proposed_next_steps_and_questions": [],
            }
        )

    monkeypatch.setattr(
        "skills.batch_audit.structured.llm_model",
        lambda: "google/gemini-2.5-pro",
    )
    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        fake_dataset_chat,
    )

    [insight] = await batch_audit(
        "example-startup",
        """# Commercial

## Traction

### Customer traction

Is there evidence of customer traction?

**Keywords:** customers, revenue
""",
        skill_name="dd_checks",
        llm_instructions="Return JSON.",
    )

    audit = json.loads(insight.content())
    assert insight.filename == "dd-checks-commercial-gemini-2-5-pro.json"
    assert insight.directory.endswith("/insights/batch-audit")
    assert audit["chapters"][0]["checks"][0]["status"] == "Fine"


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
        return json.dumps(
            {
                "industry_type": "hardware",
                "confidence": 95,
                "evidence": ["The company manufactures a device."],
            }
        )

    monkeypatch.setattr("skills.dd_checks.dd_checks.dataset_chat", fake_dataset_chat)

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
    schema = calls["kwargs"]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["industry_type"]["enum"] == [
        "biology",
        "general",
        "hardware",
        "software",
        None,
    ]
