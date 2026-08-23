from types import SimpleNamespace

import pytest

from lib.datasets import reranking
from lib.datasets.models import Chunk
from lib.datasets.reranking import rerank_chunks, reranking_enabled


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_name=f"{chunk_id}.pdf",
        page_number=1,
        last_modified=0.0,
        text=f"text {chunk_id}",
        score=0.5,
    )


@pytest.fixture
def enabled_reranker(monkeypatch):
    monkeypatch.setenv("RERANK_MODEL", "infinity/BAAI/bge-reranker-v2-m3")
    monkeypatch.setenv("RERANK_BASE_URL", "http://localhost:7997")
    monkeypatch.setenv("RERANK_API_KEY", "")


def _response(*entries):
    return SimpleNamespace(
        results=[
            {"index": index, "relevance_score": score}
            for index, score in entries
        ]
    )


def test_reranking_is_disabled_without_a_configured_model(monkeypatch):
    monkeypatch.delenv("RERANK_MODEL", raising=False)

    assert reranking_enabled() is False


def test_reranking_is_enabled_once_configured(enabled_reranker):
    assert reranking_enabled() is True


@pytest.mark.asyncio
async def test_rerank_is_skipped_when_disabled(monkeypatch, mocker):
    monkeypatch.delenv("RERANK_MODEL", raising=False)
    request = mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(),
    )
    chunks = [_chunk("a"), _chunk("b")]

    assert await rerank_chunks("query", chunks) == chunks
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerank_reorders_chunks_and_records_scores(
    enabled_reranker,
    mocker,
):
    mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(return_value=_response((2, 0.9), (0, 0.4))),
    )
    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]

    reranked = await rerank_chunks("query", chunks)

    # Reranked hits come first; chunks the provider omitted keep their order
    # behind them so reranking cannot drop recall.
    assert [chunk.chunk_id for chunk in reranked] == ["c", "a", "b"]
    assert reranked[0].score == 0.9
    assert reranked[1].score == 0.4
    assert reranked[2].score == 0.5


@pytest.mark.asyncio
async def test_rerank_sends_query_and_chunk_texts(enabled_reranker, mocker):
    request = mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(return_value=_response((0, 1.0), (1, 0.1))),
    )

    await rerank_chunks("patent ownership", [_chunk("a"), _chunk("b")])

    kwargs = request.await_args.args[0]
    assert kwargs["model"] == "infinity/BAAI/bge-reranker-v2-m3"
    assert kwargs["api_base"] == "http://localhost:7997"
    assert kwargs["query"] == "patent ownership"
    assert kwargs["documents"] == ["text a", "text b"]


@pytest.mark.asyncio
async def test_rerank_keeps_retrieval_order_when_the_provider_fails(
    enabled_reranker,
    mocker,
):
    mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(side_effect=RuntimeError("reranker unreachable")),
    )
    chunks = [_chunk("a"), _chunk("b")]

    assert await rerank_chunks("query", chunks) == chunks


@pytest.mark.asyncio
async def test_rerank_ignores_out_of_range_indices(enabled_reranker, mocker):
    mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(return_value=_response((7, 0.9), (1, 0.8))),
    )
    chunks = [_chunk("a"), _chunk("b")]

    reranked = await rerank_chunks("query", chunks)

    assert [chunk.chunk_id for chunk in reranked] == ["b", "a"]


@pytest.mark.asyncio
async def test_rerank_keeps_order_for_an_empty_result_set(
    enabled_reranker,
    mocker,
):
    mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(return_value=SimpleNamespace(results=[])),
    )
    chunks = [_chunk("a"), _chunk("b")]

    assert await rerank_chunks("query", chunks) == chunks


@pytest.mark.asyncio
async def test_rerank_skips_single_chunk_results(enabled_reranker, mocker):
    request = mocker.patch.object(
        reranking.gateway,
        "request_rerank",
        new=mocker.AsyncMock(),
    )

    assert len(await rerank_chunks("query", [_chunk("a")])) == 1
    request.assert_not_awaited()
