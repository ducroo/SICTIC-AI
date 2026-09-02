import asyncio

import pytest

from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from lib.infrastructure.scheduler import Scheduler, SchedulingTimeoutError
from lib.infrastructure.scheduler_operations import (
    JobProfile,
    register_operation,
)


def _run(
    scheduler,
    operation,
    *,
    descriptor,
    input_size=0,
    affinity_key=None,
    timeout=None,
):
    async def registered_operation():
        return await operation()

    register_operation(
        registered_operation,
        lambda _kwargs: JobProfile(
            kind="test",
            descriptor=descriptor,
            input_size=input_size,
            affinity_key=affinity_key,
        ),
    )
    return scheduler.run(
        registered_operation,
        operation_kwargs={},
        wait_timeout=timeout,
    )


@pytest.fixture
def scheduler(tmp_path):
    return Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=1,
        ollama_max_loaded_models=1,
        cloud_tpm_budget=100,
        wait_timeout=1,
        poll_interval=0.01,
    )


@pytest.mark.asyncio
async def test_run_invokes_operation_and_returns_its_result(scheduler):
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return "result"

    result = await _run(
        scheduler,
        operation,
        descriptor="docling",
        input_size=0,
    )

    assert result == "result"
    assert calls == 1
    assert all(not leases for leases in scheduler.snapshot()["leases"].values())


@pytest.mark.asyncio
async def test_run_uses_registered_inspector_and_passes_operation_kwargs(
    scheduler,
):
    async def operation(*, value):
        return value

    register_operation(
        operation,
        lambda kwargs: JobProfile(
            kind="test_kwargs",
            descriptor="docling",
            input_size=len(kwargs["value"]),
            parameters={"value_length": len(kwargs["value"])},
        ),
    )

    result = await scheduler.run(
        operation,
        operation_kwargs={"value": "result"},
    )

    assert result == "result"


@pytest.mark.asyncio
async def test_run_rejects_unregistered_operations(scheduler):
    async def operation():
        return None

    with pytest.raises(ValueError, match="Unregistered scheduler operation"):
        await scheduler.run(operation, operation_kwargs={})


@pytest.mark.asyncio
async def test_run_persists_only_derived_job_metadata(scheduler):
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation(*, secret_prompt):
        started.set()
        await release.wait()
        return secret_prompt

    register_operation(
        operation,
        lambda kwargs: JobProfile(
            kind="llm_json",
            descriptor="ollama/test",
            input_size=len(kwargs["secret_prompt"]),
            cached_input_size=3,
            affinity_key="cache-key",
            parameters={"structured": True},
        ),
    )
    task = asyncio.create_task(
        scheduler.run(
            operation,
            operation_kwargs={"secret_prompt": "private prompt"},
        )
    )
    await started.wait()

    [lease] = scheduler.snapshot()["leases"]["model"]
    assert lease["kind"] == "llm_json"
    assert lease["input_size"] == len("private prompt")
    assert lease["cached_input_size"] == 3
    assert lease["parameters"] == {"structured": True}
    assert "private prompt" not in scheduler.state_path.read_text(
        encoding="utf-8"
    )

    release.set()
    assert await task == "private prompt"


@pytest.mark.asyncio
async def test_cloud_call_is_not_blocked_by_active_ollama_model(scheduler):
    ollama_started = asyncio.Event()
    release_ollama = asyncio.Event()

    async def ollama_operation():
        ollama_started.set()
        await release_ollama.wait()

    ollama_task = asyncio.create_task(
        _run(
            scheduler,
            ollama_operation,
            descriptor="ollama/qwen3:8b",
            input_size=10,
        )
    )
    await ollama_started.wait()

    cloud_result = await _run(
        scheduler,
        lambda: asyncio.sleep(0, result="cloud-result"),
        descriptor="openai/gpt-5.6-luna",
        input_size=20,
    )

    release_ollama.set()
    await ollama_task
    assert cloud_result == "cloud-result"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active_descriptor", "waiting_descriptor"),
    [
        ("docling", "infinity/BAAI/bge-reranker-v2-m3"),
        ("infinity/BAAI/bge-reranker-v2-m3", "ollama/qwen3:8b"),
        ("ollama/qwen3:8b", "docling"),
    ],
)
async def test_local_descriptors_share_active_resource_limit(
    scheduler,
    active_descriptor,
    waiting_descriptor,
):
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_operation():
        started.set()
        await release.wait()

    active_task = asyncio.create_task(
        _run(
            scheduler,
            active_operation,
            descriptor=active_descriptor,
        )
    )
    await started.wait()

    with pytest.raises(SchedulingTimeoutError):
        await _run(
            scheduler,
            lambda: asyncio.sleep(0),
            descriptor=waiting_descriptor,
            timeout=0.03,
        )

    release.set()
    await active_task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "descriptor",
    [
        "docling",
        "infinity/BAAI/bge-reranker-v2-m3",
        "ollama/qwen3:8b",
    ],
)
async def test_local_descriptors_share_parallel_limit(scheduler, descriptor):
    started = asyncio.Event()
    release = asyncio.Event()

    async def active_operation():
        started.set()
        await release.wait()

    active_task = asyncio.create_task(
        _run(scheduler, active_operation, descriptor=descriptor)
    )
    await started.wait()

    with pytest.raises(SchedulingTimeoutError):
        await _run(
            scheduler,
            lambda: asyncio.sleep(0),
            descriptor=descriptor,
            timeout=0.03,
        )

    release.set()
    await active_task


@pytest.mark.asyncio
async def test_only_cloud_calls_consume_token_budget(scheduler):
    async def operation():
        return None

    await _run(
        scheduler,
        operation,
        descriptor="ollama/qwen3:8b",
        input_size=40,
    )
    await _run(
        scheduler,
        operation,
        descriptor="openai/gpt-5.6-luna",
        input_size=20,
    )

    assert [item["units"] for item in scheduler.snapshot()["cloud_usage"]] == [
        7
    ]


@pytest.mark.asyncio
async def test_unknown_descriptor_is_a_configuration_error(scheduler):
    async def operation():
        return None

    with pytest.raises(InfrastructureError) as raised:
        await _run(
            scheduler,
            operation,
            descriptor="unknown-service",
            input_size=0,
        )

    assert raised.value.kind is InfrastructureErrorKind.CONFIGURATION
    assert raised.value.operation == "resolve_policy"
