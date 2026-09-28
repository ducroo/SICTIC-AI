"""Dispatcher regressions: scaling, wakeups and independent callers."""
import asyncio
import multiprocessing
import threading
import time

import pytest

from lib.infrastructure.scheduler import Scheduler


def make_scheduler(path, **kwargs):
    return Scheduler(state_path=path, ollama_num_parallel=1,
                     ollama_max_loaded_models=1, wait_timeout=20, **kwargs)


async def eventually(predicate, timeout=10):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_thousands_of_waiters_share_one_polling_loop(tmp_path, mocker):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    transactions = mocker.spy(scheduler, "_dispatch_transaction")
    async with scheduler.slot("model", descriptor="ollama/test"):
        async def waiting():
            async with scheduler.slot("model", descriptor="ollama/test"):
                pytest.fail("The held slot must prevent execution")

        tasks = [asyncio.create_task(waiting()) for _ in range(2000)]
        try:
            await eventually(lambda: len(scheduler.snapshot()["requests"]["model"]) == 2000)
            dispatcher = scheduler._dispatcher
            baseline = transactions.call_count
            await asyncio.sleep(0.25)
            assert scheduler._dispatcher is dispatcher
            # One poll per interval, independent of 2,000 waiting callers.
            assert 1 <= transactions.call_count - baseline <= 8
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    state = scheduler.snapshot()
    assert not any(state["requests"].values())
    assert not any(state["leases"].values())
    assert scheduler._dispatcher is None


@pytest.mark.asyncio
async def test_release_wakes_dispatcher_without_waiting_for_poll(tmp_path):
    scheduler = make_scheduler(tmp_path / "scheduler.json", poll_interval=30)
    entered = asyncio.Event()

    async def follower():
        async with scheduler.slot("model", descriptor="ollama/test"):
            entered.set()

    async with scheduler.slot("model", descriptor="ollama/test"):
        task = asyncio.create_task(follower())
        await eventually(lambda: bool(scheduler.snapshot()["requests"]["model"]))
        assert not entered.is_set()
    await asyncio.wait_for(task, timeout=2)
    assert entered.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("failures", [1, 2, 3])
async def test_io_retries_preserve_running_heartbeat(tmp_path, mocker, failures):
    scheduler = make_scheduler(tmp_path / "scheduler.json", lease_max_age=0.6)
    original = scheduler._dispatch_transaction
    attempts = 0
    release = asyncio.Event()
    entered = asyncio.Event()

    async def waiting():
        async with scheduler.slot("model", descriptor="ollama/test"):
            entered.set()
            await release.wait()

    async with scheduler.slot("model", descriptor="ollama/test"):
        def transaction(*args):
            nonlocal attempts
            attempts += 1
            if attempts <= failures:
                raise OSError("scheduler storage unavailable")
            return original(*args)

        mocker.patch.object(scheduler, "_dispatch_transaction", side_effect=transaction)
        task = asyncio.create_task(waiting())
        try:
            if failures == 3:
                with pytest.raises(OSError, match="storage unavailable"):
                    await asyncio.wait_for(task, timeout=2)
                # A fresh waiter must still respect the original running job.
                task = asyncio.create_task(waiting())
            await eventually(lambda: attempts > failures)
            await asyncio.sleep(0.7)  # Longer than the original lease lifetime.
            assert len(scheduler.snapshot()["leases"]["model"]) == 1
            assert not entered.is_set()
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    release.set()
    await asyncio.wait_for(task, timeout=2)
    assert entered.is_set()
    assert not any(scheduler.snapshot()["leases"].values())
    assert not any(scheduler.snapshot()["requests"].values())


@pytest.mark.asyncio
async def test_three_failed_attempts_fail_waiter_before_storage_recovers(tmp_path, mocker):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    original = scheduler._dispatch_transaction
    unavailable = threading.Event()
    unavailable.set()
    attempts = 0

    def transaction(*args):
        nonlocal attempts
        if unavailable.is_set():
            attempts += 1
            raise OSError("storage offline")
        return original(*args)

    mocker.patch.object(scheduler, "_dispatch_transaction", side_effect=transaction)
    try:
        with pytest.raises(OSError, match="storage offline"):
            async with scheduler.slot("model", descriptor="ollama/test"):
                pytest.fail("Unavailable storage must prevent execution")
        assert attempts == 3
        assert scheduler._slots  # Retained for cleanup, not orphaned in shared state.
    finally:
        unavailable.clear()
    await eventually(lambda: scheduler._dispatcher is None)
    assert not any(scheduler.snapshot()["requests"].values())
    async with scheduler.slot("model", descriptor="ollama/test"):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("held", [False, True])
async def test_retry_after_committed_write_does_not_duplicate_request(tmp_path, mocker, held):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    holder = scheduler.slot("model", descriptor="ollama/test") if held else None
    if holder:
        await holder.__aenter__()
    original = scheduler._write_state
    failures = 0

    def write(state):
        nonlocal failures
        original(state)
        if failures == 0:
            failures += 1
            raise OSError("fsync failed after publication")

    mocker.patch.object(scheduler, "_write_state", side_effect=write)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def operation():
        async with scheduler.slot("model", descriptor="ollama/test"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(operation())
    try:
        await eventually(lambda: failures == 1)
        await asyncio.sleep(0.15)
        state = scheduler.snapshot()
        assert len(state["leases"]["model"]) == 1
        assert len(state["requests"]["model"]) == int(held)
        if holder:
            await holder.__aexit__(None, None, None)
            holder = None
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        release.set()
        if holder:
            await holder.__aexit__(None, None, None)
        await asyncio.wait_for(task, timeout=2)
    assert not any(scheduler.snapshot()["requests"].values())
    assert not any(scheduler.snapshot()["leases"].values())


@pytest.mark.asyncio
async def test_cancellation_during_io_retry_retains_cleanup(tmp_path, mocker):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    original = scheduler._dispatch_transaction
    failed = threading.Event()
    recover = threading.Event()

    def transaction(*args):
        if not recover.is_set():
            failed.set()
            raise OSError("storage offline")
        return original(*args)

    mocker.patch.object(scheduler, "_dispatch_transaction", side_effect=transaction)

    async def operation():
        async with scheduler.slot("model", descriptor="ollama/test"):
            pytest.fail("Cancelled operation must not start")

    task = asyncio.create_task(operation())
    try:
        await eventually(failed.is_set)
        task.cancel()
        recover.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    finally:
        recover.set()
    await eventually(lambda: scheduler._dispatcher is None)
    assert not any(scheduler.snapshot()["requests"].values())
    assert not any(scheduler.snapshot()["leases"].values())


@pytest.mark.asyncio
async def test_failed_release_remains_tracked_until_storage_recovers(tmp_path, mocker):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    holder = scheduler.slot("model", descriptor="ollama/test", affinity_key="prefix")
    await holder.__aenter__()
    original = scheduler._dispatch_transaction
    unavailable = threading.Event()
    unavailable.set()

    def transaction(*args):
        if unavailable.is_set():
            raise OSError("storage offline during release")
        return original(*args)

    mocker.patch.object(scheduler, "_dispatch_transaction", side_effect=transaction)
    try:
        with pytest.raises(OSError, match="during release"):
            await asyncio.wait_for(holder.__aexit__(None, None, None), timeout=2)
        assert scheduler._slots
    finally:
        unavailable.clear()
    await eventually(lambda: scheduler._dispatcher is None)
    state = scheduler.snapshot()
    assert not any(state["leases"].values())
    assert state["exclusive_affinity"] is None


@pytest.mark.asyncio
async def test_non_io_failure_is_not_retried(tmp_path, mocker):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    original = scheduler._dispatch_transaction
    attempts = 0

    def transaction(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("invalid scheduler state")
        return original(*args)

    mocker.patch.object(scheduler, "_dispatch_transaction", side_effect=transaction)
    with pytest.raises(ValueError, match="invalid scheduler state"):
        async with scheduler.slot("model", descriptor="ollama/test"):
            pytest.fail("Non-I/O failures must propagate")
    assert attempts == 2  # One failed dispatch and the retained cleanup fallback.
    assert scheduler._dispatcher is None


@pytest.mark.asyncio
async def test_zero_wait_timeout_still_attempts_available_capacity(tmp_path):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    async with scheduler.slot("model", descriptor="ollama/test", timeout=0):
        assert len(scheduler.snapshot()["leases"]["model"]) == 1


@pytest.mark.asyncio
async def test_running_jobs_share_heartbeat_transaction(tmp_path, mocker):
    scheduler = Scheduler(state_path=tmp_path / "scheduler.json",
                          ollama_num_parallel=20, lease_max_age=0.3)
    transactions = mocker.spy(scheduler, "_dispatch_transaction")
    release = asyncio.Event()
    entered = 0

    async def operation():
        nonlocal entered
        async with scheduler.slot("model", descriptor="ollama/test"):
            entered += 1
            await release.wait()

    tasks = [asyncio.create_task(operation()) for _ in range(20)]
    try:
        await eventually(lambda: entered == 20)
        baseline = transactions.call_count
        await asyncio.sleep(0.4)
        assert 2 <= transactions.call_count - baseline <= 6
        assert len(scheduler.snapshot()["leases"]["model"]) == 20
    finally:
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_cancel_during_grant_cleans_lease_and_affinity(tmp_path, mocker):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    original = scheduler._dispatch_transaction
    granted, resume = threading.Event(), threading.Event()

    def transaction(*args):
        result = original(*args)
        if args[0]:
            granted.set()
            assert resume.wait(5)
        return result

    mocker.patch.object(scheduler, "_dispatch_transaction", side_effect=transaction)

    async def caller():
        async with scheduler.slot("model", descriptor="ollama/test", affinity_key="prefix"):
            pytest.fail("Cancelled operation must never execute")

    task = asyncio.create_task(caller())
    try:
        assert await asyncio.to_thread(granted.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        resume.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = scheduler.snapshot()
    assert not any(state["leases"].values())
    assert state["exclusive_affinity"] is None


def test_shared_instance_serves_simultaneous_event_loops(tmp_path):
    scheduler = make_scheduler(tmp_path / "scheduler.json")
    barrier = threading.Barrier(4)
    lock = threading.Lock()
    running = 0
    peak = 0
    errors = []

    async def operation():
        nonlocal running, peak
        async with scheduler.slot("model", descriptor="ollama/test"):
            with lock:
                running += 1
                peak = max(peak, running)
            await asyncio.sleep(0.02)
            with lock:
                running -= 1

    def worker():
        try:
            barrier.wait(timeout=5)
            asyncio.run(operation())
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert peak == 1
    assert scheduler._dispatcher is None
    # Reuse after earlier event loops have closed.
    asyncio.run(operation())


def _process_worker(path, ready, release, finished):
    async def run():
        scheduler = make_scheduler(path)
        async with scheduler.slot("model", descriptor="ollama/test"):
            ready.set()
            await asyncio.to_thread(release.wait, 10)
        finished.set()
    asyncio.run(run())


@pytest.mark.parametrize("crash", [False, True])
def test_processes_share_capacity_and_recover_after_exit(tmp_path, crash):
    context = multiprocessing.get_context("spawn")
    path = str(tmp_path / "scheduler.json")
    ready = [context.Event(), context.Event()]
    release = [context.Event(), context.Event()]
    finished = [context.Event(), context.Event()]
    workers = [context.Process(target=_process_worker, args=(path, ready[i], release[i], finished[i]))
               for i in range(2)]
    try:
        workers[0].start()
        assert ready[0].wait(10)
        workers[1].start()
        scheduler = make_scheduler(path)
        deadline = time.monotonic() + 10
        while not scheduler.snapshot()["requests"]["model"]:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert not ready[1].is_set()
        if crash:
            workers[0].terminate()
            workers[0].join(5)
        else:
            release[0].set()
            assert finished[0].wait(5)
        assert ready[1].wait(5)
        release[1].set()
        assert finished[1].wait(5)
        assert not any(scheduler.snapshot()["leases"].values())
    finally:
        # A terminated child may leave its Event's semaphore locked.
        for worker, event in zip(workers, release):
            if worker.is_alive():
                event.set()
        for worker in workers:
            if worker.pid is not None:
                worker.join(5)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
