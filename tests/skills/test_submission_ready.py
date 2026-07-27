import pytest

from skills.submission_ready.submission_ready import run_submission_query


@pytest.mark.asyncio
async def test_submission_query_returns_strict_schema(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return (
            '{"judgment":"Pass","assessment":"Founder submitted it.",'
            '"source_documents":["Dealum Application — Contact"],'
            '"proposed_next_step":"No action"}'
        )

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.dataset_chat",
        fake_dataset_chat,
    )

    result = await run_submission_query(
        "example",
        "Was it submitted by a founder?",
        "1.1",
        "Return JSON.",
    )

    assert result == {
        "judgment": "Pass",
        "assessment": "Founder submitted it.",
        "source_documents": "Dealum Application — Contact",
        "proposed_next_step": "No action",
    }


@pytest.mark.asyncio
async def test_submission_query_keeps_missing_evidence_unclear(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return "INSUFFICIENT_CONTEXT"

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.dataset_chat",
        fake_dataset_chat,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._fallback_trigger",
        lambda: "INSUFFICIENT_CONTEXT",
    )

    result = await run_submission_query(
        "example",
        "What is the valuation?",
        "5.1",
        "Return JSON.",
    )

    assert result["judgment"] == "Unclear"
    assert "does not establish" in result["assessment"]
    assert result["source_documents"] == "None"


@pytest.mark.asyncio
async def test_submission_query_normalizes_invalid_judgment_to_unclear(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return (
            '{"judgment":"Probably","assessment":"Maybe",'
            '"source_documents":[],"proposed_next_step":"Review"}'
        )

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.dataset_chat",
        fake_dataset_chat,
    )

    result = await run_submission_query(
        "example",
        "What is the valuation?",
        "5.1",
        "Return JSON.",
    )

    assert result["judgment"] == "Unclear"
    assert "invalid judgment" in result["assessment"]
