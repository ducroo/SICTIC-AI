import pytest
from aiohttp.test_utils import TestClient, TestServer

from spike.purge_auth_users import PurgeResult
from spike.web import create_app


@pytest.mark.asyncio
async def test_purge_auth_api_requires_admin_token(monkeypatch):
    monkeypatch.setenv("SPIKE_ADMIN_TOKEN", "secret-token")
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/admin/purge-auth-users")
        body = await response.json()
    assert response.status == 401
    assert "Admin token" in body["error"]


@pytest.mark.asyncio
async def test_purge_auth_api_runs_dry_run(monkeypatch, mocker):
    monkeypatch.setenv("SPIKE_ADMIN_TOKEN", "secret-token")
    mocker.patch(
        "spike.web.purge_auth_users_older_than",
        return_value=PurgeResult(
            retention_days=60,
            scanned=2,
            deleted=1,
            dry_run=True,
            deleted_emails=("old@example.com",),
        ),
    )
    app = create_app()
    async with TestClient(TestServer(app)) as client:
        response = await client.post(
            "/api/admin/purge-auth-users",
            json={"dry_run": True, "days": 60},
            headers={"X-Spike-Admin-Token": "secret-token"},
        )
        body = await response.json()
    assert response.status == 200
    assert body["scanned"] == 2
    assert body["deleted"] == 1
    assert body["dry_run"] is True
