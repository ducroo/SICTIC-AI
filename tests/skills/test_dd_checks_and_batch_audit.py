import json

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from skills.batch_audit.batch_audit import batch_audit
from skills.dd_checks.dd_checks import find_industry_type, parse_industry_type


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
    )

    audit = json.loads(insight.content())
    assert insight.filename == "dd-checks-commercial-gemini-2-5-pro.json"
    assert insight.directory.endswith("/insights/batch-audit")
    assert audit["chapters"][0]["checks"][0]["status"] == "Fine"


def test_parse_industry_type_uses_explicit_label_not_rationale():
    response = (
        "Industry Type: Software Confidence Score: 95%\n"
        "The rationale mentions Biology only as a contrasting category."
    )

    result = parse_industry_type(response, {"biology", "hardware", "software", "general"})

    assert result == "software"


def test_parse_industry_type_defaults_to_general_when_unparseable():
    result = parse_industry_type("No clear answer", {"biology", "hardware", "software", "general"})

    assert result == "general"


@pytest.mark.asyncio
async def test_find_industry_type_uses_default_retrieval_chunk_count(monkeypatch):
    calls = {}

    async def fake_dataset_chat(*args, **kwargs):
        calls["kwargs"] = kwargs
        return "Industry Type: Hardware Confidence Score: 95%"

    monkeypatch.setattr("skills.dd_checks.dd_checks.dataset_chat", fake_dataset_chat)

    result = await find_industry_type(
        "proud-technology",
        {
            "industry_type_query": "classify the startup",
            "industry_type_llm_instructions": "choose one industry type",
        },
        {"biology", "general", "hardware", "software"},
    )

    assert result == "hardware"
    assert "max_chunks" not in calls["kwargs"]
