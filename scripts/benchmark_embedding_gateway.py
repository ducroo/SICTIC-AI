"""Live benchmark for embedding gateway lease and call timing."""

from __future__ import annotations

import asyncio
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm
import typer

from lib.logger import get_logger
from lib.model_config import embedding_endpoint
from lib.services_gateway import GatewayTimeoutError, ServicesGateway

logger = get_logger(__name__)
app = typer.Typer(help="Benchmark live embedding gateway timing.")


@dataclass
class ChunkTiming:
    chunk_id: int
    register_start: float
    register_end: float
    acquire_start: float
    lease_acquired: float
    embedding_start: float
    embedding_end: float
    release_start: float
    release_end: float
    vector_size: int

    @property
    def register_ms(self) -> float:
        return _ms(self.register_end - self.register_start)

    @property
    def queue_ms(self) -> float:
        return _ms(self.lease_acquired - self.register_end)

    @property
    def embedding_ms(self) -> float:
        return _ms(self.embedding_end - self.embedding_start)

    @property
    def release_ms(self) -> float:
        return _ms(self.release_end - self.release_start)

    @property
    def lease_total_ms(self) -> float:
        return _ms(self.release_end - self.lease_acquired)


def _ms(seconds: float) -> float:
    return seconds * 1000.0


def _summary(values: list[float]) -> str:
    if not values:
        return "n/a"
    return (
        f"min={min(values):.1f} p50={statistics.median(values):.1f} "
        f"max={max(values):.1f} mean={statistics.mean(values):.1f}"
    )


def _chunk_text(chunk_id: int, repeat: int) -> str:
    sentence = (
        f"Chunk {chunk_id}: NovoViz develops computational single-photon "
        "image sensors with on-chip processing for machine vision, quantum "
        "imaging, and space domain awareness. "
    )
    return sentence * repeat


async def _sample_leases(
    gateway: ServicesGateway,
    done: asyncio.Event,
    sample_interval_ms: float,
) -> list[tuple[float, int]]:
    samples: list[tuple[float, int]] = []
    while not done.is_set():
        state = await asyncio.to_thread(gateway.snapshot)
        running = len(state["leases"]["embedding"])
        samples.append((time.perf_counter(), running))
        await asyncio.sleep(sample_interval_ms / 1000.0)
    state = await asyncio.to_thread(gateway.snapshot)
    samples.append((time.perf_counter(), len(state["leases"]["embedding"])))
    return samples


async def _timed_embedding(
    chunk_id: int,
    text: str,
    gateway: ServicesGateway,
    kwargs_template: dict[str, Any],
    timeout: float,
) -> ChunkTiming:
    model = str(kwargs_template["model"])
    register_start = time.perf_counter()
    request, _counts, _active_models = await asyncio.to_thread(
        gateway._register_request,
        "embedding",
        model,
    )
    register_end = time.perf_counter()

    lease = None
    acquire_start = time.perf_counter()
    started = time.monotonic()
    try:
        while True:
            lease, _counts, _active_models = await asyncio.to_thread(
                gateway._try_acquire,
                request,
                max_concurrent=gateway.ollama_num_parallel,
            )
            if lease is not None:
                break
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                state = await asyncio.to_thread(gateway.snapshot)
                occupancy = {
                    name: len(items)
                    for name, items in state["leases"].items()
                }
                raise GatewayTimeoutError(
                    f"Timed out after {elapsed:.1f}s waiting for embedding; "
                    f"active leases: {occupancy}"
                )
            await asyncio.sleep(gateway.poll_interval)

        lease_acquired = time.perf_counter()
        kwargs = dict(kwargs_template)
        kwargs["input"] = [text]
        embedding_start = time.perf_counter()
        response = await litellm.aembedding(**kwargs)
        embedding_end = time.perf_counter()
        vector_size = len(response.data[0]["embedding"])
    finally:
        release_start = time.perf_counter()
        if lease is None:
            await asyncio.to_thread(gateway._remove_request, request)
        else:
            await asyncio.to_thread(gateway._release, lease)
        release_end = time.perf_counter()

    return ChunkTiming(
        chunk_id=chunk_id,
        register_start=register_start,
        register_end=register_end,
        acquire_start=acquire_start,
        lease_acquired=lease_acquired,
        embedding_start=embedding_start,
        embedding_end=embedding_end,
        release_start=release_start,
        release_end=release_end,
        vector_size=vector_size,
    )


async def _run_benchmark(
    *,
    chunks: int,
    repeat: int,
    state_path: Path,
    sample_interval_ms: float,
    gateway_poll_ms: float | None,
    timeout: float,
) -> None:
    endpoint = embedding_endpoint()
    kwargs_template = endpoint.litellm_kwargs()
    kwargs_template["model"] = endpoint.model
    gateway_kwargs: dict[str, Any] = {"state_path": state_path}
    if gateway_poll_ms is not None:
        gateway_kwargs["poll_interval"] = gateway_poll_ms / 1000.0
    gateway = ServicesGateway(**gateway_kwargs)
    litellm.disable_aiohttp_transport = True

    texts = [_chunk_text(index, repeat) for index in range(1, chunks + 1)]
    done = asyncio.Event()
    sampler = asyncio.create_task(
        _sample_leases(gateway, done, sample_interval_ms)
    )
    batch_start = time.perf_counter()
    try:
        timings = await asyncio.gather(
            *(
                _timed_embedding(
                    index,
                    text,
                    gateway,
                    kwargs_template,
                    timeout,
                )
                for index, text in enumerate(texts, start=1)
            )
        )
    finally:
        done.set()
    samples = await sampler
    batch_end = time.perf_counter()

    max_running = max((running for _ts, running in samples), default=0)
    print(f"model: {endpoint.model}")
    print(f"api_base: {endpoint.base_url or 'provider default'}")
    print(f"gateway_state: {state_path}")
    print(f"chunks: {chunks}")
    print(f"chunk_repeat: {repeat}")
    print(f"gateway_capacity: {gateway.ollama_num_parallel}")
    print(f"gateway_poll_ms: {gateway.poll_interval * 1000.0:.1f}")
    print(f"sample_interval_ms: {sample_interval_ms}")
    print(f"batch_wall_ms: {_ms(batch_end - batch_start):.1f}")
    print(f"max_sampled_embedding_leases: {max_running}")
    print()
    print(
        "chunk register_ms queue_ms embed_ms release_ms lease_total_ms "
        "vector_size"
    )
    for timing in sorted(timings, key=lambda item: item.chunk_id):
        print(
            f"{timing.chunk_id:>5} "
            f"{timing.register_ms:>11.1f} "
            f"{timing.queue_ms:>8.1f} "
            f"{timing.embedding_ms:>8.1f} "
            f"{timing.release_ms:>10.1f} "
            f"{timing.lease_total_ms:>14.1f} "
            f"{timing.vector_size:>11}"
        )
    print()
    print(f"register_ms: {_summary([item.register_ms for item in timings])}")
    print(f"queue_ms: {_summary([item.queue_ms for item in timings])}")
    print(f"embed_ms: {_summary([item.embedding_ms for item in timings])}")
    print(f"release_ms: {_summary([item.release_ms for item in timings])}")
    print(
        "lease_total_ms: "
        f"{_summary([item.lease_total_ms for item in timings])}"
    )


@app.command()
def main(
    chunks: int = typer.Option(7, "--chunks", help="Number of chunks."),
    repeat: int = typer.Option(
        40,
        "--repeat",
        help="Sentence repetitions per synthetic chunk.",
    ),
    sample_interval_ms: float = typer.Option(
        1.0,
        "--sample-interval-ms",
        help="Gateway lease sampling interval.",
    ),
    gateway_poll_ms: float | None = typer.Option(
        None,
        "--gateway-poll-ms",
        help="Override gateway lease retry polling interval.",
    ),
    timeout: float = typer.Option(
        60.0,
        "--timeout",
        help="Seconds to wait for a gateway lease.",
    ),
    state_path: Path | None = typer.Option(
        None,
        "--state-path",
        help="Gateway state path. Defaults to an isolated temp file.",
    ),
) -> None:
    """Run a live embedding batch and print timing diagnostics."""
    if chunks < 1:
        raise typer.BadParameter("chunks must be at least 1")
    if repeat < 1:
        raise typer.BadParameter("repeat must be at least 1")
    selected_state_path = state_path or Path(tempfile.gettempdir()) / (
        f"sictic-embedding-gateway-benchmark-{time.time_ns()}.json"
    )
    logger.info(
        "Running embedding gateway benchmark with %s chunks, repeat=%s",
        chunks,
        repeat,
    )
    try:
        asyncio.run(
            _run_benchmark(
                chunks=chunks,
                repeat=repeat,
                state_path=selected_state_path,
                sample_interval_ms=sample_interval_ms,
                gateway_poll_ms=gateway_poll_ms,
                timeout=timeout,
            )
        )
    except Exception as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()
