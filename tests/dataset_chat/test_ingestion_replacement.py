from types import SimpleNamespace

import pytest

from lib.datasets.indexing import replace_document


@pytest.mark.asyncio
async def test_replacement_upserts_before_deleting_stale_chunks():
    events = []
    chunks = [
        SimpleNamespace(
            chunk_id="chunk-1",
            text="first",
            model_dump=lambda: {"document_name": "report.pdf"},
        ),
        SimpleNamespace(
            chunk_id="chunk-2",
            text="second",
            model_dump=lambda: {"document_name": "report.pdf"},
        ),
    ]

    class Embeddings:
        async def embed_many(self, texts):
            events.append(("embed", texts))
            return [[1.0], [2.0]]

    qdrant = SimpleNamespace(
        get_document_point_ids=lambda name: events.append(("get", name)) or {"old"},
        upsert_points=lambda points: events.append(("upsert", points)),
        delete_point_ids=lambda ids: events.append(("delete", ids)),
    )

    await replace_document(
        qdrant,
        Embeddings(),
        "report.pdf",
        chunks,
    )

    assert [event[0] for event in events] == ["get", "embed", "upsert", "delete"]
    assert events[-1] == ("delete", {"old"})
    assert events[2][1][0]["payload"] == {"document_name": "report.pdf"}


@pytest.mark.asyncio
async def test_embedding_failure_keeps_existing_chunks():
    events = []

    class Embeddings:
        async def embed_many(self, _texts):
            raise RuntimeError("embedding unavailable")

    qdrant = SimpleNamespace(
        get_document_point_ids=lambda _name: set(),
        upsert_points=lambda _points: events.append("upsert"),
        delete_point_ids=lambda _ids: events.append("delete"),
    )

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await replace_document(
            qdrant,
            Embeddings(),
            "report.pdf",
            [SimpleNamespace(text="text")],
        )

    assert events == []


@pytest.mark.asyncio
async def test_partial_upsert_failure_keeps_existing_chunks():
    events = []
    chunks = [
        SimpleNamespace(
            chunk_id="new",
            text="replacement",
            model_dump=lambda: {"document_name": "report.pdf"},
        )
    ]

    class Embeddings:
        async def embed_many(self, _texts):
            return [[1.0]]

    def fail_upsert(_points):
        events.append("upsert")
        raise RuntimeError("second batch failed")

    qdrant = SimpleNamespace(
        get_document_point_ids=lambda _name: {"old"},
        upsert_points=fail_upsert,
        delete_point_ids=lambda _ids: events.append("delete"),
    )

    with pytest.raises(RuntimeError, match="second batch failed"):
        await replace_document(qdrant, Embeddings(), "report.pdf", chunks)

    assert events == ["upsert"]
