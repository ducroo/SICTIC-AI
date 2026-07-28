import pytest

from skills.batch_audit.batch_audit import run_audit_query
from skills.dd_checks.dd_checks import find_industry_type, parse_industry_type


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


@pytest.mark.asyncio
async def test_batch_audit_disables_strict_insufficient_context(monkeypatch):
    calls = {}

    async def fake_dataset_chat(*args, **kwargs):
        calls["kwargs"] = kwargs
        return '{"status": "Not Found", "summary": "Not Found", "concerns": "None"}'

    monkeypatch.setattr("skills.batch_audit.batch_audit.dataset_chat", fake_dataset_chat)

    result = await run_audit_query("bewe", "question", "1.1", "json instructions")

    assert calls["kwargs"]["strict_insufficient_context"] is False
    assert result == {"status": "Not Found", "summary": "Not Found", "concerns": "None"}


@pytest.mark.asyncio
async def test_batch_audit_normalizes_fallback_marker(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return "INSUFFICIENT_CONTEXT"

    monkeypatch.setattr("skills.batch_audit.batch_audit.dataset_chat", fake_dataset_chat)
    monkeypatch.setattr(
        "skills.batch_audit.batch_audit._fallback_trigger",
        lambda: "INSUFFICIENT_CONTEXT",
    )

    result = await run_audit_query("bewe", "question", "1.1", "json instructions")

    assert result == {"status": "Not Found", "summary": "Not Found", "concerns": "None"}


@pytest.mark.asyncio
async def test_batch_audit_reports_llm_request_failures(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        raise RuntimeError("No available accounts")

    monkeypatch.setattr("skills.batch_audit.batch_audit.dataset_chat", fake_dataset_chat)

    result = await run_audit_query("bewe", "question", "1.1", "json instructions")

    assert result["status"] == "Error"
    assert result["summary"] == "LLM request failed: No available accounts"
    assert result["concerns"] == "N/A"


@pytest.mark.asyncio
async def test_batch_audit_reports_json_parse_failures(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return "not json"

    monkeypatch.setattr("skills.batch_audit.batch_audit.dataset_chat", fake_dataset_chat)

    result = await run_audit_query("bewe", "question", "1.1", "json instructions")

    assert result["status"] == "Error"
    assert result["summary"].startswith("Failed to parse LLM response:")
    assert result["concerns"] == "N/A"
