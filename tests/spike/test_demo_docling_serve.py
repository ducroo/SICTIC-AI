from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.infrastructure.fake_docling_serve import MINIMAL_PDF, create_app as create_fake_docling_app


class MemoryStore:
    def __init__(self, *args, **kwargs):
        self.points: list[dict] = []
        self.collection_name = "temp"

    def collection_exists(self) -> bool:
        return bool(self.points)

    def sparse_enabled(self) -> bool:
        return False

    def ensure_collection(self, vector_size: int) -> None:
        return None

    def get_document_mtimes(self, *, raise_on_error: bool = False) -> dict:
        return {}

    def get_document_point_ids(self, document_name: str) -> set[str]:
        return {
            point["id"]
            for point in self.points
            if point["payload"].get("document_name") == document_name
        }

    def delete_point_ids(self, point_ids: set[str]) -> None:
        wanted = set(point_ids)
        self.points = [point for point in self.points if point["id"] not in wanted]

    def delete_document(self, document_name: str, *, raise_on_error: bool = False) -> None:
        self.points = [
            point
            for point in self.points
            if point["payload"].get("document_name") != document_name
        ]

    def upsert_points(self, points: list[dict], *, batch_size: int = 50) -> set[str]:
        for point in points:
            self.delete_point_ids({point["id"]})
            self.points.append(point)
        return {point["id"] for point in points}

    def query(self, vector, *, limit: int):
        return [
            SimpleNamespace(
                id=point["id"],
                score=1.0,
                payload=dict(point["payload"]),
            )
            for point in self.points[:limit]
        ]

    def delete_collection(self) -> None:
        self.points.clear()

    def delete_dataset(self, dataset_slug: str | None = None) -> bool:
        self.points.clear()
        return True


class FakeEmbeddings:
    model = "test-embedding"

    async def vector_size(self) -> int:
        return 4

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


async def _start_fake_docling():
    from aiohttp import web

    app = create_fake_docling_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def _patch_ingest(mocker, store: MemoryStore) -> None:
    mocker.patch("lib.ephemeral_dataset.QdrantAdapter", return_value=store)
    mocker.patch("lib.datasets.indexing.QdrantAdapter", return_value=store)
    mocker.patch("lib.datasets.search.QdrantAdapter", return_value=store)
    mocker.patch("lib.datasets.indexing.EmbeddingService", return_value=FakeEmbeddings())
    mocker.patch("lib.datasets.search.EmbeddingService", return_value=FakeEmbeddings())


@pytest.mark.asyncio
async def test_api_demo_pdf_upload_converts_through_docling_serve(
    monkeypatch, mocker, mock_env
):
    from spike.web import create_app

    runner, base_url = await _start_fake_docling()
    store = MemoryStore()
    _patch_ingest(mocker, store)
    monkeypatch.setenv("DOCUMENT_PARSER", "docling")
    monkeypatch.setenv("DOCUMENT_CONVERTER", "docling_serve")
    monkeypatch.setenv("DOCLING_SERVE_URL", base_url)
    monkeypatch.setenv("VECTOR_STORE", "qdrant")
    try:
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/api/demo",
                json={
                    "query": "CET1 capital ratio",
                    "filename": "acme.pdf",
                    "content_base64": base64.b64encode(MINIMAL_PDF).decode("ascii"),
                },
            )
            payload = await response.json()
            assert response.status == 200, payload
            assert payload["dataset_name"] == "temp"
            texts = " ".join(hit["text"] for hit in payload["hits"])
            assert "Acme Robotics" in texts
            assert "CET1 capital ratio" in texts
            assert payload["hits"][0]["document_name"] == "acme.pdf"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_api_demo_still_accepts_markdown_json(mocker, mock_env):
    from spike.web import create_app

    store = MemoryStore()
    _patch_ingest(mocker, store)
    async with TestClient(TestServer(create_app())) as client:
        response = await client.post(
            "/api/demo",
            json={"query": "Acme", "markdown": "# Acme Robotics\n\nBuilds arms.\n"},
        )
        payload = await response.json()
        assert response.status == 200, payload
        texts = " ".join(hit["text"] for hit in payload["hits"])
        assert "Acme Robotics" in texts


@pytest.mark.asyncio
async def test_get_root_serves_hosting_spa():
    from spike.web import create_app

    async with TestClient(TestServer(create_app())) as client:
        response = await client.get("/")
        body = await response.text()
        assert response.status == 200
        assert 'id="file"' in body
        assert "Search a file or pasted markdown" in body


@pytest.mark.asyncio
async def test_get_demo_serves_python_form():
    from spike.web import create_app

    async with TestClient(TestServer(create_app())) as client:
        response = await client.get("/demo")
        body = await response.text()
        assert response.status == 200
        assert 'enctype="multipart/form-data"' in body
        assert "Converter" in body
