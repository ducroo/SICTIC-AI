import asyncio
import json
import os
import time

import pytest

from lib.infrastructure.errors import InfrastructureError
from lib.infrastructure.scheduler import (
    Scheduler,
    SchedulingTimeoutError,
    default_scheduler_state_path,
)
from lib.infrastructure.scheduler_operations import (
    JobProfile,
    register_operation,
)


def _run(scheduler, operation, *, descriptor, input_size=0):
    async def registered_operation():
        return await operation()

    register_operation(
        registered_operation,
        lambda _kwargs: JobProfile(
            kind="test",
            descriptor=descriptor,
            input_size=input_size,
        ),
    )
    return scheduler.run(registered_operation, operation_kwargs={})


@pytest.fixture
def clean_scheduler(tmp_path):
    return Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=2,
        wait_timeout=1,
        poll_interval=0.01,
    )


def _leases(scheduler, resource):
    return scheduler.snapshot()["leases"][resource]


def _requests(scheduler, resource):
    return scheduler.snapshot()["requests"][resource]


def test_default_state_path_uses_local_data_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_DATA_PATH", str(tmp_path))
    path = default_scheduler_state_path()

    assert path == tmp_path / "cache" / "scheduler.json"


def test_default_poll_interval_is_fifty_milliseconds(tmp_path):
    scheduler = Scheduler(state_path=tmp_path / "scheduler.json")

    assert scheduler.poll_interval == 0.05


def test_scheduler_initialization_has_no_file_side_effect(clean_scheduler):
    assert not clean_scheduler.state_path.exists()

    state = clean_scheduler.snapshot()

    assert state == {
        "version": 10,
        "leases": {
            "docling": [],
            "model": [],
            "embedding": [],
            "llm": [],
            "rerank": [],
        },
        "requests": {
            "docling": [],
            "model": [],
            "embedding": [],
            "llm": [],
            "rerank": [],
        },
        "cloud_usage": [],
        "exclusive_affinity": None,
    }


def test_atomic_write_preserves_previous_state_when_replace_fails(
    clean_scheduler,
    mocker,
):
    request = clean_scheduler._register_request("llm", "model")[0]
    previous = clean_scheduler.state_path.read_text(encoding="utf-8")
    replace = mocker.patch(
        "lib.infrastructure.scheduler_state.os.replace",
        side_effect=OSError("replace failed"),
    )

    with pytest.raises(OSError, match="replace failed"):
        clean_scheduler._with_locked_state(
            lambda state: state["cloud_usage"].append(
                {"request_time": time.time(), "units": 1}
            )
        )

    assert clean_scheduler.state_path.read_text(encoding="utf-8") == previous
    mocker.stop(replace)
    clean_scheduler._remove_request(request)


def test_cloud_budget_is_shared_across_services_and_expires(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=2,
        cloud_tpm_budget=10,
    )
    first = scheduler._register_request(
        "llm",
        "openai/model",
        budget_units=7,
    )[0]
    waiting = scheduler._register_request(
        "embedding",
        "openai/embedding-model",
        budget_units=4,
    )[0]

    first_lease, _, _ = scheduler._try_acquire(first)
    assert first_lease is not None
    scheduler._release(first_lease)

    blocked, _, _ = scheduler._try_acquire(waiting)
    assert blocked is None
    assert scheduler.snapshot()["cloud_usage"] == [
        {
            "request_time": pytest.approx(time.time(), abs=1),
            "units": 7,
        }
    ]

    scheduler._with_locked_state(
        lambda state: state["cloud_usage"][0].update(
            {"request_time": time.time() - 61}
        )
    )
    waiting_lease, _, _ = scheduler._try_acquire(waiting)

    assert waiting_lease is not None
    assert [item["units"] for item in scheduler.snapshot()["cloud_usage"]] == [4]
    scheduler._release(waiting_lease)


@pytest.mark.asyncio
async def test_scheduler_estimates_cloud_requests_but_not_local_requests(
    tmp_path,
):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=3,
        cloud_tpm_budget=100,
    )

    async def complete():
        return "completion"

    await _run(
        scheduler,
        complete,
        descriptor="openai/model",
        input_size=10,
    )
    await _run(
        scheduler,
        complete,
        descriptor="openai/embedding",
        input_size=6,
    )
    await _run(
        scheduler,
        complete,
        descriptor="openai/rerank",
        input_size=9,
    )
    await _run(
        scheduler,
        complete,
        descriptor="ollama/local",
        input_size=10,
    )

    assert [item["units"] for item in scheduler.snapshot()["cloud_usage"]] == [
        4,
        2,
        3,
    ]


@pytest.mark.asyncio
async def test_request_larger_than_cloud_budget_fails_immediately(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        cloud_tpm_budget=10,
    )

    with pytest.raises(InfrastructureError, match="exceeds CLOUD_TPM_BUDGET"):
        async with scheduler.slot(
            "llm",
            model="openai/model",
            budget_units=11,
        ):
            pass


@pytest.mark.asyncio
async def test_scheduler_allows_distinct_models_to_run_together(
    clean_scheduler,
):
    llm_started = asyncio.Event()
    release_llm = asyncio.Event()
    embedding_started = asyncio.Event()
    release_embedding = asyncio.Event()

    async def mock_llm_completion():
        llm_started.set()
        await release_llm.wait()
        return "Mocked LLM"

    async def mock_embedding():
        embedding_started.set()
        await release_embedding.wait()
        return "Mocked Embedding"

    llm_task = asyncio.create_task(
        _run(
            clean_scheduler,
            mock_llm_completion,
            descriptor="ollama/llm",
            input_size=0,
        )
    )
    await llm_started.wait()
    assert len(_leases(clean_scheduler, "model")) == 1

    embed_task = asyncio.create_task(
        _run(
            clean_scheduler,
            mock_embedding,
            descriptor="ollama/embed",
        )
    )
    await embedding_started.wait()
    assert len(_leases(clean_scheduler, "model")) == 2

    release_llm.set()
    release_embedding.set()
    await llm_task
    await embed_task

    assert _leases(clean_scheduler, "model") == []


@pytest.mark.asyncio
async def test_scheduler_concurrency_limits_are_per_model(clean_scheduler):
    active = 0
    maximum_active = 0
    active_lock = asyncio.Lock()

    async def mock_slow_embedding():
        nonlocal active, maximum_active
        async with active_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.05)
        async with active_lock:
            active -= 1
        return "Mock"

    await asyncio.gather(
        *(
            _run(
                clean_scheduler,
                mock_slow_embedding,
                descriptor="ollama/embed",
            )
            for _ in range(4)
        )
    )

    assert maximum_active == 2
    assert _leases(clean_scheduler, "model") == []


@pytest.mark.asyncio
async def test_first_poll_grants_all_available_slots_in_fifo_order(
    clean_scheduler,
):
    first = clean_scheduler._register_request("llm", "first-model")[0]
    second = clean_scheduler._register_request("embedding", "second-model")[0]

    second_lease, _, _ = clean_scheduler._try_acquire(second)

    assert second_lease is not None
    state = clean_scheduler.snapshot()
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

    first_lease, _, _ = clean_scheduler._try_acquire(first)

    assert first_lease is not None
    clean_scheduler._release(second_lease)
    clean_scheduler._release(first_lease)


def test_affinity_runs_first_request_exclusively_then_drains_matching_queue(
    clean_scheduler,
):
    first = clean_scheduler._register_request(
        "model",
        "openai/model",
        max_concurrent=1,
        affinity_key="shared-prefix",
    )[0]
    unrelated = clean_scheduler._register_request(
        "model",
        "openai/other-model",
        max_concurrent=1,
    )[0]
    follower = clean_scheduler._register_request(
        "model",
        "openai/model",
        max_concurrent=1,
        affinity_key="shared-prefix",
    )[0]

    first_lease, _, _ = clean_scheduler._try_acquire(first)
    blocked, _, _ = clean_scheduler._try_acquire(unrelated)

    assert first_lease is not None
    assert blocked is None
    assert clean_scheduler.snapshot()["exclusive_affinity"]["phase"] == (
        "warming"
    )

    clean_scheduler._release(first_lease)
    clean_scheduler._try_acquire(unrelated)
    follower_lease, _, _ = clean_scheduler._try_acquire(follower)

    assert follower_lease is not None
    assert clean_scheduler.snapshot()["exclusive_affinity"] is None
    clean_scheduler._release(follower_lease)
    unrelated_lease, _, _ = clean_scheduler._try_acquire(unrelated)
    assert unrelated_lease is not None
    clean_scheduler._release(unrelated_lease)


def test_failed_affinity_warmup_releases_exclusivity(clean_scheduler):
    first = clean_scheduler._register_request(
        "model",
        "openai/model",
        affinity_key="shared-prefix",
    )[0]
    follower = clean_scheduler._register_request(
        "model",
        "openai/model",
        affinity_key="shared-prefix",
    )[0]
    first_lease, _, _ = clean_scheduler._try_acquire(first)

    assert first_lease is not None
    clean_scheduler._release(first_lease, succeeded=False)

    assert clean_scheduler.snapshot()["exclusive_affinity"] is None
    clean_scheduler._remove_request(follower)


def test_unsuccessful_acquisition_does_not_rewrite_state(
    clean_scheduler,
    mocker,
):
    first = clean_scheduler._register_request(
        "embedding",
        "embedding-model",
        max_concurrent=1,
    )[0]
    waiting = clean_scheduler._register_request(
        "embedding",
        "embedding-model",
        max_concurrent=1,
    )[0]
    first_lease, _, _ = clean_scheduler._try_acquire(first)
    assert first_lease is not None
    write_state = mocker.patch.object(
        clean_scheduler,
        "_write_state",
        wraps=clean_scheduler._write_state,
    )

    blocked, _, _ = clean_scheduler._try_acquire(waiting)

    assert blocked is None
    write_state.assert_not_called()
    clean_scheduler._remove_request(waiting)
    clean_scheduler._release(first_lease)


def test_one_poll_fills_embedding_capacity(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=16,
        ollama_max_loaded_models=1,
    )
    requests = [
        scheduler._register_request("embedding", "embedding-model")[0]
        for _ in range(100)
    ]

    first_lease, _, _ = scheduler._try_acquire(requests[0])

    assert first_lease is not None
    assert len(_leases(scheduler, "embedding")) == 16
    assert len(_requests(scheduler, "embedding")) == 84
    scheduler._release(first_lease)
    for request in requests[1:16]:
        lease, _, _ = scheduler._try_acquire(request)
        assert lease is not None
        scheduler._release(lease)
    for request in requests[16:]:
        scheduler._remove_request(request)


@pytest.mark.asyncio
async def test_blocked_request_does_not_cause_head_of_line_blocking(
    tmp_path,
):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )
    active = scheduler._register_request("llm", "loaded-model")[0]
    active_lease, _, _ = scheduler._try_acquire(active)
    assert active_lease is not None

    blocked = scheduler._register_request("embedding", "blocked-model")[0]
    runnable = scheduler._register_request("llm", "loaded-model")[0]

    runnable_lease, _, _ = scheduler._try_acquire(runnable)

    assert runnable_lease is not None
    scheduler._remove_request(blocked)
    scheduler._release(runnable_lease)
    scheduler._release(active_lease)


@pytest.mark.asyncio
async def test_same_resource_different_models_have_independent_capacity(
    clean_scheduler,
):
    requests = [
        clean_scheduler._register_request("llm", model)[0]
        for model in ("model-a", "model-a", "model-b", "model-b")
    ]
    leases = [
        clean_scheduler._try_acquire(request)[0]
        for request in requests
    ]

    assert all(lease is not None for lease in leases)
    assert len(_leases(clean_scheduler, "llm")) == 4
    for lease in leases:
        clean_scheduler._release(lease)


@pytest.mark.asyncio
async def test_llm_capacity_matches_ollama_num_parallel(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=9,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )
    slots = [
        scheduler.slot("llm", model="ollama/same")
        for _ in range(scheduler.ollama_num_parallel)
    ]
    try:
        for slot in slots:
            await slot.__aenter__()
        assert len(_leases(scheduler, "llm")) == scheduler.ollama_num_parallel

        with pytest.raises(SchedulingTimeoutError):
            async with scheduler.slot(
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
    clean_scheduler,
):
    requests = [
        clean_scheduler._register_request("llm", "same-model")[0]
        for _ in range(2)
    ]
    waiting = clean_scheduler._register_request("embedding", "same-model")[0]

    leases = [
        clean_scheduler._try_acquire(request)[0]
        for request in requests
    ]
    blocked_lease, _, _ = clean_scheduler._try_acquire(waiting)

    assert all(lease is not None for lease in leases)
    assert blocked_lease is None
    clean_scheduler._remove_request(waiting)
    for lease in leases:
        clean_scheduler._release(lease)


def test_state_checks_each_process_identity_once(clean_scheduler, mocker):
    requests = [
        clean_scheduler._register_request("embedding", "embedding-model")[0]
        for _ in range(3)
    ]
    process_check = mocker.patch.object(
        clean_scheduler,
        "_lease_is_alive",
        wraps=clean_scheduler._lease_is_alive,
    )

    clean_scheduler.snapshot()

    assert process_check.call_count == 1
    for request in requests:
        clean_scheduler._remove_request(request)


@pytest.mark.asyncio
async def test_slot_releases_lease_after_cancellation(clean_scheduler):
    entered = asyncio.Event()

    async def hold_slot():
        async with clean_scheduler.slot(
            "llm",
            affinity_key="shared-prefix",
        ):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold_slot())
    await entered.wait()
    assert len(_leases(clean_scheduler, "llm")) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _leases(clean_scheduler, "llm") == []
    assert clean_scheduler.snapshot()["exclusive_affinity"] is None


@pytest.mark.asyncio
async def test_active_slot_heartbeats_prevent_lease_expiry(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        lease_max_age=0.09,
        poll_interval=0.01,
    )

    async with scheduler.slot("llm"):
        await asyncio.sleep(0.15)
        assert len(_leases(scheduler, "llm")) == 1

    assert _leases(scheduler, "llm") == []


@pytest.mark.asyncio
async def test_slot_removes_waiting_request_after_cancellation(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with scheduler.slot("llm", model="ollama/loaded"):
        waiting = asyncio.create_task(
            scheduler.slot(
                "embedding",
                model="ollama/blocked",
            ).__aenter__()
        )
        await asyncio.sleep(0.05)
        assert len(_requests(scheduler, "embedding")) == 1

        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert _requests(scheduler, "embedding") == []


@pytest.mark.asyncio
async def test_slot_times_out_with_occupancy(clean_scheduler):
    async with clean_scheduler.slot("llm", max_concurrent=1):
        with pytest.raises(SchedulingTimeoutError, match="active leases"):
            async with clean_scheduler.slot(
                "llm",
                max_concurrent=1,
                timeout=0.03,
            ):
                pass
        assert _requests(clean_scheduler, "llm") == []


@pytest.mark.asyncio
async def test_scheduler_logs_counts_when_request_arrives_and_starts(
    clean_scheduler,
    caplog,
):
    with caplog.at_level("INFO", logger="lib.infrastructure.scheduler"):
        async with clean_scheduler.slot("llm"):
            pass

    assert (
        "Scheduler request received: llm 0 running, 1 waiting | "
        "local resources 0/2 active"
    ) in caplog.text
    assert (
        "Scheduler job started: llm 1 running, 0 waiting | "
        "local resources 0/2 active"
    ) in caplog.text


@pytest.mark.asyncio
async def test_same_model_requests_share_loaded_model_slot(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with scheduler.slot("llm", model="ollama/same", max_concurrent=2):
        async with scheduler.slot("llm", model="ollama/same", max_concurrent=2):
            leases = _leases(scheduler, "llm")
            assert len(leases) == 2
            assert {lease["descriptor"] for lease in leases} == {
                "ollama/same"
            }


@pytest.mark.asyncio
async def test_different_model_waits_when_loaded_model_slots_are_full(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=1,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with scheduler.slot("llm", model="ollama/first", max_concurrent=2):
        with pytest.raises(SchedulingTimeoutError):
            async with scheduler.slot(
                "llm",
                model="ollama/second",
                max_concurrent=2,
                timeout=0.03,
            ):
                pass


@pytest.mark.asyncio
async def test_three_services_share_model_slots_equally(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
        ollama_num_parallel=2,
        ollama_max_loaded_models=3,
        wait_timeout=1,
        poll_interval=0.01,
    )

    async with scheduler.slot("llm", model="ollama/llm-model"):
        async with scheduler.slot(
            "embedding",
            model="ollama/embedding-model",
        ):
            async with scheduler.slot(
                "docling",
                model="ollama/docling-model",
            ):
                assert len(scheduler.snapshot()["leases"]["llm"]) == 1
                assert len(scheduler.snapshot()["leases"]["embedding"]) == 1
                assert len(scheduler.snapshot()["leases"]["docling"]) == 1
                assert scheduler._active_local_descriptors(
                    scheduler.snapshot()
                ) == {
                    "ollama/llm-model",
                    "ollama/embedding-model",
                    "ollama/docling-model",
                }


def test_expired_lease_from_live_process_is_reclaimed(tmp_path):
    scheduler = Scheduler(
        state_path=tmp_path / "scheduler.json",
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
            "process_start": scheduler._process_start,
            "acquired_at": acquired_at,
        }

    scheduler.state_path.parent.mkdir(parents=True, exist_ok=True)
    scheduler.state_path.write_text(
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

    remaining = _leases(scheduler, "llm")

    assert [lease["lease_id"] for lease in remaining] == ["fresh"]


def test_dead_or_reused_pid_lease_is_cleaned(clean_scheduler):
    clean_scheduler.state_path.parent.mkdir(parents=True, exist_ok=True)
    clean_scheduler.state_path.write_text(
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

    assert _leases(clean_scheduler, "llm") == []
    assert _requests(clean_scheduler, "embedding") == []
