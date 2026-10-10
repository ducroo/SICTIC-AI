import asyncio

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from spike.web import create_app


@pytest.mark.asyncio
async def test_api_review_requires_app_check_when_enabled(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "1")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "0")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    mocker.patch(
        "spike.web.verify_app_check_token",
        side_effect=ValueError("App Check token is missing."),
    )
    app = create_app()
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/review", data=form)
        body = await response.json()

    assert response.status == 401
    assert "App Check" in body["error"]


@pytest.mark.asyncio
async def test_api_review_accepts_a_valid_app_check_token(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "1")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "0")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")
    mocker.patch(
        "spike.web.verify_app_check_token",
        return_value={"sub": "1:224218759787:web:test"},
    )

    async def fake_review(*, filename, payload, on_progress=None):
        if on_progress is not None:
            on_progress("extract")
            on_progress("review")
        return "# Pitch deck review\n\n| No | Check | Status |\n| --- | --- | --- |\n| 1.1 | Team | Fine |\n"

    mocker.patch("spike.web.review_pitch_deck_upload", side_effect=fake_review)
    app = create_app()
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    async with TestClient(TestServer(app)) as client:
        start = await client.post(
            "/api/review",
            data=form,
            headers={"X-Firebase-AppCheck": "token"},
        )
        started = await start.json()
        assert start.status == 200
        job_id = started["job_id"]
        for _ in range(40):
            status = await client.get(
                f"/api/review/{job_id}",
                headers={"X-Firebase-AppCheck": "token"},
            )
            payload = await status.json()
            if payload.get("done"):
                break
            await asyncio.sleep(0.05)

    assert payload["done"] is True
    assert "report_html" in payload
    assert 'class="status-fine"' in payload["report_html"]


@pytest.mark.asyncio
async def test_legacy_review_start_stays_open_without_app_check(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "1")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "review-deck-a3c26")

    async def fake_review(*, filename, payload, on_progress=None):
        if on_progress is not None:
            on_progress("extract")
            on_progress("review")
        return "# Pitch deck review\n\nFine.\n"

    mocker.patch("spike.web.review_pitch_deck_upload", side_effect=fake_review)
    app = create_app()
    form = FormData()
    form.add_field("deck", b"%PDF-1.4", filename="deck.pdf", content_type="application/pdf")
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/review/start", data=form)
        body = await response.json()

    assert response.status == 200
    assert body["job_id"]


@pytest.mark.asyncio
async def test_api_review_sets_cors_for_hosting_origin(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "0")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "0")
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
            headers={"Origin": "https://review-deck-a3c26.web.app"},
        )
        options = await client.options(
            "/api/review",
            headers={
                "Origin": "https://review-deck-a3c26.web.app",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.headers.get("Access-Control-Allow-Origin") == (
        "https://review-deck-a3c26.web.app"
    )
    assert options.status == 204
    assert options.headers.get("Access-Control-Allow-Origin") == (
        "https://review-deck-a3c26.web.app"
    )
