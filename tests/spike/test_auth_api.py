import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from spike.web import create_app


@pytest.mark.asyncio
async def test_api_review_requires_auth_when_enabled(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "0")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    mocker.patch(
        "spike.web.verify_id_token",
        side_effect=ValueError("Sign-in is required."),
    )
    app = create_app()
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/review", data=form)
        body = await response.json()

    assert response.status == 401
    assert "Sign-in" in body["error"]


@pytest.mark.asyncio
async def test_api_review_accepts_valid_auth_and_app_check(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "1")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    mocker.patch(
        "spike.web.verify_app_check_token",
        return_value={"sub": "1:224218759787:web:test"},
    )
    mocker.patch(
        "spike.web.verify_id_token",
        return_value={"sub": "user-123", "email": "founder@example.com"},
    )
    mocker.patch(
        "spike.web.review_pitch_deck_upload",
        return_value="# Pitch deck review\n\nFine.\n",
    )
    app = create_app()
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/review",
            data=form,
            headers={
                "X-Firebase-AppCheck": "app-check-token",
                "Authorization": "Bearer id-token",
            },
        )
        body = await response.json()

    assert response.status == 200
    assert body["job_id"]
