import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from spike.web import create_app


ORIGIN = "https://review.sictic.ch"


@pytest.mark.asyncio
async def test_api_options_includes_cors_for_review_origin():
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        response = await client.options(
            "/api/review",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,x-firebase-appcheck",
            },
        )

    assert response.status == 204
    assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN


@pytest.mark.asyncio
async def test_oversized_upload_still_returns_cors(monkeypatch):
    monkeypatch.setenv("SPIKE_REQUIRE_APP_CHECK", "0")
    monkeypatch.setenv("SPIKE_REQUIRE_AUTH", "0")
    app = create_app()
    app._client_max_size = 1024
    form = FormData()
    form.add_field("review_kind", "dataroom")
    form.add_field(
        "dataroom",
        b"x" * 5000,
        filename="room.zip",
        content_type="application/zip",
    )
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/review",
            data=form,
            headers={"Origin": ORIGIN},
        )
        body = await response.text()

    assert response.status == 413
    assert response.headers.get("Access-Control-Allow-Origin") == ORIGIN
    assert "Maximum request body size" in body
