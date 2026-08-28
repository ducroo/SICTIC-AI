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


def test_default_state_path_uses_local_data_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path))
    path = default_gateway_state_path()

    assert path == tmp_path / "cache" / "services-gateway.json"


def test_default_poll_interval_is_fifty_milliseconds(tmp_path):
    gateway = ServicesGateway(state_path=tmp_path / "gateway.json")

    assert gateway.poll_interval == 0.05


def test_lease_max_age_covers_llm_request_timeout(monkeypatch, tmp_path):
    monkeypatch.delenv("GATEWAY_LEASE_MAX_AGE", raising=False)
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "7200")
    monkeypatch.setenv("LLM_STRUCTURED_REQUEST_TIMEOUT", "180")
    gateway = ServicesGateway(state_path=tmp_path / "gateway.json")

    assert gateway.lease_max_age == 7200.0


def test_gateway_initialization_has_no_file_side_effect(clean_gateway):
    assert not clean_gateway.state_path.exists()

    state = clean_gateway.snapshot()

    assert state == {
        "version": 6,
        "leases": {"docling": [], "embedding": [], "llm": [], "rerank": []},
        "requests": {"docling": [], "embedding": [], "llm": [], "rerank": []},
        "cloud_usage": [],
    }


def test_cloud_budget_is_shared_across_services_and_expires(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=2,
        cloud_tpm_budget=10,
    )
    first = gateway._register_request(
        "llm",
        "openai/model",
        budget_units=7,
    )[0]
    waiting = gateway._register_request(
        "embedding",
        "openai/embedding-model",
        budget_units=4,
    )[0]

    first_lease, _, _ = gateway._try_acquire(first, max_concurrent=2)
    assert first_lease is not None
    gateway._release(first_lease)

    blocked, _, _ = gateway._try_acquire(waiting, max_concurrent=2)
    assert blocked is None
    assert gateway.snapshot()["cloud_usage"] == [
        {
            "request_time": pytest.approx(time.time(), abs=1),
            "units": 7,
        }
    ]

    gateway._with_locked_state(
        lambda state: state["cloud_usage"][0].update(
            {"request_time": time.time() - 61}
        )
    )
    waiting_lease, _, _ = gateway._try_acquire(
        waiting,
        max_concurrent=2,
    )

    assert waiting_lease is not None
    assert [item["units"] for item in gateway.snapshot()["cloud_usage"]] == [4]
    gateway._release(waiting_lease)


@pytest.mark.asyncio
async def test_gateway_estimates_cloud_requests_but_not_local_requests(
    tmp_path,
    mocker,
):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=3,
        cloud_tpm_budget=100,
    )
    mocker.patch("litellm.acompletion", return_value="completion")
    mocker.patch("litellm.aembedding", return_value="embedding")
    mocker.patch("litellm.arerank", return_value="rerank")

    await gateway.request_completion(
        {
            "model": "openai/model",
            "messages": [{"role": "user", "content": "123456"}],
        }
    )
    await gateway.request_embedding(
        {"model": "openai/embedding", "input": ["123456"]}
    )
    await gateway.request_rerank(
        {
            "model": "openai/rerank",
            "query": "123",
            "documents": ["123456"],
        }
    )
    await gateway.request_completion(
        {
            "model": "ollama/local",
            "messages": [{"role": "user", "content": "123456"}],
        }
    )

    assert [item["units"] for item in gateway.snapshot()["cloud_usage"]] == [
        4,
        2,
        3,
    ]


@pytest.mark.asyncio
async def test_request_larger_than_cloud_budget_fails_immediately(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        cloud_tpm_budget=10,
    )

    with pytest.raises(ValueError, match="exceeds CLOUD_TPM_BUDGET"):
        async with gateway.slot(
            "llm",
            model="openai/model",
            budget_units=11,
        ):
            pass


@pytest.mark.asyncio
async def test_gateway_allows_distinct_models_to_run_together(
    clean_gateway,
    mocker,
):
    llm_started = asyncio.Event()
    release_llm = asyncio.Event()
    embedding_started = asyncio.Event()
    release_embedding = asyncio.Event()

    async def mock_llm_completion(**kwargs):
        llm_started.set()
        await release_llm.wait()
        return "Mocked LLM"

    async def mock_embedding(**kwargs):
        embedding_started.set()
        await release_embedding.wait()
        return "Mocked Embedding"

    mocker.patch("litellm.acompletion", side_effect=mock_llm_completion)
    mocker.patch("litellm.aembedding", side_effect=mock_embedding)

    llm_task = asyncio.create_task(
        clean_gateway.request_completion({"model": "ollama/llm"})
    )
    await llm_started.wait()
    assert len(_leases(clean_gateway, "llm")) == 1

    embed_task = asyncio.create_task(
        clean_gateway.request_embedding({"model": "ollama/embed"})
    )
    await embedding_started.wait()
    assert len(_leases(clean_gateway, "embedding")) == 1

    release_llm.set()
    release_embedding.set()
    await llm_task
    await embed_task

    assert _leases(clean_gateway, "llm") == []
    assert _leases(clean_gateway, "embedding") == []


@pytest.mark.asyncio
async def test_gateway_concurrency_limits_are_per_model(clean_gateway, mocker):
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
        *(
            clean_gateway.request_embedding({"model": "ollama/embed"})
            for _ in range(4)
        )
    )

    assert maximum_active == 2
    assert _leases(clean_gateway, "embedding") == []


@pytest.mark.asyncio
async def test_first_poll_grants_all_available_slots_in_fifo_order(
    clean_gateway,
):
    first = clean_gateway._register_request("llm", "first-model")[0]
    second = clean_gateway._register_request("embedding", "second-model")[0]

    second_lease, _, _ = clean_gateway._try_acquire(
        second,
        max_concurrent=2,
    )

    assert second_lease is not None
    state = clean_gateway.snapshot()
    granted = sorted(
        (
            lease
            for leases in state["leases"].values()
            for lease in leases
        ),
        key=lambda lease: lease["acquired_at"],
    )
    assert [lease["request_id"] for lease in granted] == [
        first.request_id,
        second.request_id,
    ]
    assert all(not queue for queue in state["requests"].values())

    first_lease, _, _ = clean_gateway._try_acquire(first, max_concurrent=2)

    assert first_lease is not None
    clean_gateway._release(second_lease)
    clean_gateway._release(first_lease)


def test_unsuccessful_acquisition_does_not_rewrite_state(
    clean_gateway,
    mocker,
):
    first = clean_gateway._register_request(
        "embedding",
        "embedding-model",
        max_concurrent=1,
    )[0]
    waiting = clean_gateway._register_request(
        "embedding",
        "embedding-model",
        max_concurrent=1,
    )[0]
    first_lease, _, _ = clean_gateway._try_acquire(
        first,
        max_concurrent=1,
    )
    assert first_lease is not None
    write_state = mocker.patch.object(
        clean_gateway,
        "_write_state",
        wraps=clean_gateway._write_state,
    )

    blocked, _, _ = clean_gateway._try_acquire(
        waiting,
        max_concurrent=1,
    )

    assert blocked is None
    write_state.assert_not_called()
    clean_gateway._remove_request(waiting)
    clean_gateway._release(first_lease)


def test_one_poll_fills_embedding_capacity(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=16,
        ollama_max_loaded_models=1,
    )
    requests = [
        gateway._register_request("embedding", "embedding-model")[0]
        for _ in range(100)
    ]

    first_lease, _, _ = gateway._try_acquire(
        requests[0],
        max_concurrent=16,
    )

    assert first_lease is not None
    assert len(_leases(gateway, "embedding")) == 16
    assert len(_requests(gateway, "embedding")) == 84
    gateway._release(first_lease)
    for request in requests[1:16]:
        lease, _, _ = gateway._try_acquire(
            request,
            max_concurrent=16,
        )
        assert lease is not None
        gateway._release(lease)
    for request in requests[16:]:
        gateway._remove_request(request)


@pytest.mark.asyncio
async def test_blocked_request_does_not_cause_head_of_line_blocking(
    tmp_path,
):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )
    active = gateway._register_request("llm", "loaded-model")[0]
    active_lease, _, _ = gateway._try_acquire(active, max_concurrent=2)
    assert active_lease is not None

    blocked = gateway._register_request("embedding", "blocked-model")[0]
    runnable = gateway._register_request("llm", "loaded-model")[0]

    runnable_lease, _, _ = gateway._try_acquire(
        runnable,
        max_concurrent=2,
    )

    assert runnable_lease is not None
    gateway._remove_request(blocked)
    gateway._release(runnable_lease)
    gateway._release(active_lease)


@pytest.mark.asyncio
async def test_same_resource_different_models_have_independent_capacity(
    clean_gateway,
):
    requests = [
        clean_gateway._register_request("llm", model)[0]
        for model in ("model-a", "model-a", "model-b", "model-b")
    ]
    leases = [
        clean_gateway._try_acquire(request, max_concurrent=2)[0]
        for request in requests
    ]

    assert all(lease is not None for lease in leases)
    assert len(_leases(clean_gateway, "llm")) == 4
    for lease in leases:
        clean_gateway._release(lease)


@pytest.mark.asyncio
async def test_llm_capacity_matches_ollama_num_parallel(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=9,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )
    slots = [
        gateway.slot("llm", model="ollama/same")
        for _ in range(gateway.ollama_num_parallel)
    ]
    try:
        for slot in slots:
            await slot.__aenter__()
        assert len(_leases(gateway, "llm")) == gateway.ollama_num_parallel

        with pytest.raises(GatewayTimeoutError):
            async with gateway.slot(
                "llm",
                model="ollama/same",
                timeout=0.03,
            ):
                pass
    finally:
        for slot in reversed(slots):
            await slot.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_same_model_respects_per_model_capacity(
    clean_gateway,
):
    requests = [
        clean_gateway._register_request("llm", "same-model")[0]
        for _ in range(2)
    ]
    waiting = clean_gateway._register_request("embedding", "same-model")[0]

    leases = [
        clean_gateway._try_acquire(request, max_concurrent=2)[0]
        for request in requests
    ]
    blocked_lease, _, _ = clean_gateway._try_acquire(
        waiting,
        max_concurrent=2,
    )

    assert all(lease is not None for lease in leases)
    assert blocked_lease is None
    clean_gateway._remove_request(waiting)
    for lease in leases:
        clean_gateway._release(lease)


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
async def test_slot_removes_waiting_request_after_cancellation(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with gateway.slot("llm", model="loaded"):
        waiting = asyncio.create_task(
            gateway.slot("embedding", model="blocked").__aenter__()
        )
        await asyncio.sleep(0.05)
        assert len(_requests(gateway, "embedding")) == 1

        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert _requests(gateway, "embedding") == []


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
        "embedding 0 running, 0 waiting | rerank 0 running, 0 waiting | "
        "docling 0 running, 0 waiting | models 0/2 loaded"
    ) in caplog.text
    assert (
        "Gateway job started: LLM 1 running, 0 waiting | "
        "embedding 0 running, 0 waiting | rerank 0 running, 0 waiting | "
        "docling 0 running, 0 waiting | models 1/2 loaded"
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


@pytest.mark.asyncio
async def test_three_services_share_model_slots_equally(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=3,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with gateway.slot("llm", model="llm-model"):
        async with gateway.slot("embedding", model="embedding-model"):
            async with gateway.slot("docling", model="docling-model"):
                assert len(gateway.snapshot()["leases"]["llm"]) == 1
                assert len(gateway.snapshot()["leases"]["embedding"]) == 1
                assert len(gateway.snapshot()["leases"]["docling"]) == 1
                assert gateway._active_models(gateway.snapshot()) == {
                    "llm-model",
                    "embedding-model",
                    "docling-model",
                }


def test_expired_lease_from_live_process_is_reclaimed(tmp_path):
    gateway = ServicesGateway(
        state_path=tmp_path / "gateway.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=2,
        wait_timeout=1,
        poll_interval=0.01,
        lease_max_age=60,
    )

    def make_lease(lease_id, acquired_at):
        return {
            "lease_id": lease_id,
            "resource": "llm",
            "model": "llm",
            "pid": os.getpid(),
            "process_start": gateway._process_start,
            "acquired_at": acquired_at,
        }

    gateway.state_path.parent.mkdir(parents=True, exist_ok=True)
    gateway.state_path.write_text(
        json.dumps(
            {
                "version": 4,
                "leases": {
                    "docling": [],
                    "embedding": [],
                    "llm": [
                        make_lease("expired", time.time() - 3600),
                        make_lease("fresh", time.time()),
                    ],
                },
                "requests": {"docling": [], "embedding": [], "llm": []},
            }
        ),
        encoding="utf-8",
    )

    remaining = _leases(gateway, "llm")

    assert [lease["lease_id"] for lease in remaining] == ["fresh"]


@pytest.mark.asyncio
async def test_completion_applies_default_request_timeout(
    clean_gateway,
    mocker,
):
    completion = mocker.patch(
        "litellm.acompletion",
        return_value="Mocked LLM",
    )

    await clean_gateway.request_completion({"model": "ollama/llm"})

    assert completion.call_args.kwargs["timeout"] == 3600.0


@pytest.mark.asyncio
async def test_caller_request_timeout_is_preserved(clean_gateway, mocker):
    embedding = mocker.patch(
        "litellm.aembedding",
        return_value="Mocked Embedding",
    )

    await clean_gateway.request_embedding(
        {"model": "ollama/embed", "timeout": 42}
    )

    assert embedding.call_args.kwargs["timeout"] == 42


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
