import asyncio
import json
import os
import time

import pytest

from lib.services_gateway import (
    GatewayTimeoutError,
    ServicesGateway,
    default_gateway_state_path,
)


@pytest.fixture
def clean_gateway(tmp_path):
    return ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=2,
        wait_timeout=1,
        poll_interval=0.01,
    )


def _leases(gateway, resource):
    return gateway.snapshot()["leases"][resource]


def _requests(gateway, resource):
    return gateway.snapshot()["requests"][resource]


def test_default_state_path_is_repo_scoped_and_machine_local():
    path = default_gateway_state_path()

    assert "sictic-ai" in path.parts
    assert path.name == "services-gateway.json"
    assert len(path.parent.name) == 16


def test_gateway_initialization_has_no_file_side_effect(clean_gateway):
    assert not clean_gateway.state_path.exists()

    state = clean_gateway.snapshot()

    assert state == {
        "version": 4,
        "leases": {"docling": [], "embedding": [], "llm": []},
        "requests": {"docling": [], "embedding": [], "llm": []},
    }


@pytest.mark.asyncio
async def test_gateway_mode_switching(clean_gateway, mocker):
    llm_started = asyncio.Event()
    release_llm = asyncio.Event()
    embedding_started = asyncio.Event()

    async def mock_llm_completion(**kwargs):
        llm_started.set()
        await release_llm.wait()
        return "Mocked LLM"

    async def mock_embedding(**kwargs):
        embedding_started.set()
        return "Mocked Embedding"

    mocker.patch("litellm.acompletion", side_effect=mock_llm_completion)
    mocker.patch("litellm.aembedding", side_effect=mock_embedding)

    llm_task = asyncio.create_task(clean_gateway.request_completion({}))
    await llm_started.wait()
    assert len(_leases(clean_gateway, "llm")) == 1

    embed_task = asyncio.create_task(clean_gateway.request_embedding({}))
    await asyncio.sleep(0.05)
    assert not embedding_started.is_set()
    assert _leases(clean_gateway, "embedding") == []
    assert len(_requests(clean_gateway, "embedding")) == 1

    release_llm.set()
    await llm_task
    await embed_task

    assert _leases(clean_gateway, "llm") == []
    assert _leases(clean_gateway, "embedding") == []
    assert _requests(clean_gateway, "embedding") == []


@pytest.mark.asyncio
async def test_gateway_concurrency_limits(clean_gateway, mocker):
    active = 0
    maximum_active = 0
    active_lock = asyncio.Lock()

    async def mock_slow_embedding(**kwargs):
        nonlocal active, maximum_active
        async with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.05)
        async with active_lock:
            active -= 1
        return "Mock"

    mocker.patch("litellm.aembedding", side_effect=mock_slow_embedding)

    await asyncio.gather(
        *(clean_gateway.request_embedding({}) for _ in range(4))
    )

    assert maximum_active == 2
    assert _leases(clean_gateway, "embedding") == []


@pytest.mark.asyncio
async def test_available_capacity_does_not_wait_for_each_queue_head(
    clean_gateway,
):
    requests = [
        clean_gateway._register_request("embedding", "embedding-model")[0]
        for _ in range(2)
    ]

    second_lease, _, _ = clean_gateway._try_acquire(
        requests[1],
        max_concurrent=2,
    )

    assert second_lease is not None
    clean_gateway._remove_request(requests[0])
    clean_gateway._release(second_lease)


def test_state_checks_each_process_identity_once(clean_gateway, mocker):
    requests = [
        clean_gateway._register_request("embedding", "embedding-model")[0]
        for _ in range(3)
    ]
    process_check = mocker.patch.object(
        clean_gateway,
        "_lease_is_alive",
        wraps=clean_gateway._lease_is_alive,
    )

    clean_gateway.snapshot()

    assert process_check.call_count == 1
    for request in requests:
        clean_gateway._remove_request(request)


@pytest.mark.asyncio
async def test_slot_releases_lease_after_cancellation(clean_gateway):
    entered = asyncio.Event()

    async def hold_slot():
        async with clean_gateway.slot("llm"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold_slot())
    await entered.wait()
    assert len(_leases(clean_gateway, "llm")) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _leases(clean_gateway, "llm") == []


@pytest.mark.asyncio
async def test_slot_removes_waiting_request_after_cancellation(clean_gateway):
    async with clean_gateway.slot("llm"):
        waiting = asyncio.create_task(clean_gateway.slot("embedding").__aenter__())
        await asyncio.sleep(0.05)
        assert len(_requests(clean_gateway, "embedding")) == 1

        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert _requests(clean_gateway, "embedding") == []


@pytest.mark.asyncio
async def test_slot_times_out_with_occupancy(clean_gateway):
    async with clean_gateway.slot("llm", max_concurrent=1):
        with pytest.raises(GatewayTimeoutError, match="active leases"):
            async with clean_gateway.slot(
                "llm",
                max_concurrent=1,
                timeout=0.03,
            ):
                pass
        assert _requests(clean_gateway, "llm") == []


@pytest.mark.asyncio
async def test_gateway_logs_counts_when_request_arrives_and_starts(
    clean_gateway,
    caplog,
):
    with caplog.at_level("INFO", logger="lib.services_gateway"):
        async with clean_gateway.slot("llm"):
            pass

    assert (
        "Gateway request received: LLM 0 running, 1 waiting | "
        "embedding 0 running, 0 waiting | docling 0 running, 0 waiting | "
        "models 0/2 loaded"
    ) in caplog.text
    assert (
        "Gateway job started: LLM 1 running, 0 waiting | "
        "embedding 0 running, 0 waiting | docling 0 running, 0 waiting | "
        "models 1/2 loaded"
    ) in caplog.text


@pytest.mark.asyncio
async def test_same_model_requests_share_loaded_model_slot(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with gateway.slot("llm", model="ollama/same", max_concurrent=2):
        async with gateway.slot("llm", model="ollama/same", max_concurrent=2):
            leases = _leases(gateway, "llm")
            assert len(leases) == 2
            assert {lease["model"] for lease in leases} == {"ollama/same"}


@pytest.mark.asyncio
async def test_different_model_waits_when_loaded_model_slots_are_full(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with gateway.slot("llm", model="ollama/first", max_concurrent=2):
        with pytest.raises(GatewayTimeoutError):
            async with gateway.slot(
                "llm",
                model="ollama/second",
                max_concurrent=2,
                timeout=0.03,
            ):
                pass


def test_dead_or_reused_pid_lease_is_cleaned(clean_gateway):
    clean_gateway.state_path.parent.mkdir(parents=True, exist_ok=True)
    clean_gateway.state_path.write_text(
        json.dumps(
            {
                "version": 3,
                "leases": {
                    "docling": [],
                    "embedding": [],
                    "llm": [
                        {
                            "lease_id": "stale",
                            "resource": "llm",
                            "model": "llm",
                            "pid": os.getpid(),
                            "process_start": "wrong-process-instance",
                            "acquired_at": time.time(),
                        }
                    ],
                },
                "requests": {
                    "docling": [],
                    "embedding": [
                        {
                            "request_id": "stale-request",
                            "resource": "embedding",
                            "model": "embedding",
                            "pid": os.getpid(),
                            "process_start": "wrong-process-instance",
                            "requested_at": time.time(),
                        }
                    ],
                    "llm": [],
                },
            }
        ),
        encoding="utf-8",
    )

    assert _leases(clean_gateway, "llm") == []
    assert _requests(clean_gateway, "embedding") == []
