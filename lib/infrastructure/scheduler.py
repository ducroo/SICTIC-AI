"""Cross-process capacity scheduling for infrastructure operations."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import subprocess
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypeVar

from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from lib.infrastructure.logging import get_logger
from lib.infrastructure.scheduler_operations import inspect_operation
from lib.infrastructure.scheduler_policy import SchedulerPolicy
from lib.infrastructure.scheduler_state import SchedulerStateStore

logger = get_logger(__name__)

T = TypeVar("T")

_RESOURCE_KEYS = ("docling", "model", "embedding", "llm", "rerank")
_DEFAULT_WAIT_TIMEOUT = 3600.0
_POLL_INTERVAL = 0.05
# Active slots refresh their lease periodically. A lease without a recent
# heartbeat is reclaimed even when its process remains alive.
_DEFAULT_LEASE_MAX_AGE = 1800.0


def _float_env(name: str, default: float) -> float:
    raw = get_env_var(name, required=False)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise InfrastructureError(
            f"Environment variable {name!r} must be numeric, got {raw!r}",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="scheduler",
            operation="load_configuration",
        ) from error


def _int_env(name: str, default: int) -> int:
    raw = get_env_var(name, required=False)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise InfrastructureError(
            f"Environment variable {name!r} must be an integer, got {raw!r}",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="scheduler",
            operation="load_configuration",
        ) from error


class SchedulingTimeoutError(InfrastructureError):
    """Raised when capacity does not become available before the deadline."""

    def __init__(self, message: str) -> None:
        InfrastructureError.__init__(
            self,
            message,
            kind=InfrastructureErrorKind.RESOURCE_BUSY,
            provider="scheduler",
            operation="acquire_capacity",
        )


@dataclass(frozen=True)
class SchedulerLease:
    lease_id: str
    request_id: str
    resource: str
    descriptor: str
    pid: int
    process_start: str
    acquired_at: float
    heartbeat_at: float
    affinity_key: str | None = None
    kind: str = "operation"
    input_size: int = 0
    cached_input_size: int = 0
    parameters: dict[str, object] | None = None


@dataclass(frozen=True)
class SchedulerRequest:
    request_id: str
    resource: str
    descriptor: str
    pid: int
    process_start: str
    requested_at: float
    max_concurrent: int
    budget_units: int = 0
    affinity_key: str | None = None
    kind: str = "operation"
    input_size: int = 0
    cached_input_size: int = 0
    parameters: dict[str, object] | None = None


def default_scheduler_state_path() -> Path:
    """Return the scheduler state path under the repository-local cache."""
    local_data_root = (
        get_env_var("LOCAL_DATA_PATH", required=False)
        or get_env_var("REPO_PATH", required=False)
        or Path(__file__).resolve().parents[2]
    )
    return (
        Path(local_data_root).expanduser().resolve()
        / "cache"
        / "scheduler.json"
    )


def _process_start_token(pid: int) -> str | None:
    """Identify a process instance, not merely a reusable PID."""
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            fields = proc_stat.read_text(encoding="utf-8").split()
            return fields[21]
        except (OSError, IndexError):
            return None
    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = completed.stdout.strip()
    return token or None


class Scheduler:
    """Coordinate provider capacity across independent CLI processes."""

    def __init__(
        self,
        *,
        state_path: str | os.PathLike | None = None,
        ollama_num_parallel: int | None = None,
        ollama_max_loaded_models: int | None = None,
        wait_timeout: float = _DEFAULT_WAIT_TIMEOUT,
        poll_interval: float = _POLL_INTERVAL,
        lease_max_age: float | None = None,
        cloud_tpm_budget: int | None = None,
    ):
        self.state_path = Path(
            state_path or default_scheduler_state_path()
        ).expanduser()
        self._state_store = SchedulerStateStore(self.state_path)
        self.ollama_num_parallel = (
            ollama_num_parallel
            if ollama_num_parallel is not None
            else _int_env("OLLAMA_NUM_PARALLEL", 1)
        )
        self.ollama_max_loaded_models = (
            ollama_max_loaded_models
            if ollama_max_loaded_models is not None
            else _int_env("OLLAMA_MAX_LOADED_MODELS", 1)
        )
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.lease_max_age = (
            lease_max_age
            if lease_max_age is not None
            else _float_env(
                "SCHEDULER_LEASE_MAX_AGE",
                _DEFAULT_LEASE_MAX_AGE,
            )
        )
        self.cloud_tpm_budget = (
            cloud_tpm_budget
            if cloud_tpm_budget is not None
            else _int_env("CLOUD_TPM_BUDGET", 0)
        )
        if self.lease_max_age <= 0:
            raise ValueError("lease_max_age must be positive")
        self._policy = SchedulerPolicy(
            default_capacity=self.ollama_num_parallel,
            max_loaded_models=self.ollama_max_loaded_models,
            cloud_tpm_budget=self.cloud_tpm_budget,
        )
        self._process_start = _process_start_token(os.getpid()) or str(
            time.time_ns()
        )

    def _empty_state(self) -> dict:
        return {
            "version": 10,
            "leases": {resource: [] for resource in _RESOURCE_KEYS},
            "requests": {resource: [] for resource in _RESOURCE_KEYS},
            "cloud_usage": [],
            "exclusive_affinity": None,
        }

    def _lease_is_alive(self, lease: dict) -> bool:
        try:
            pid = int(lease["pid"])
            expected_start = str(lease["process_start"])
        except (KeyError, TypeError, ValueError):
            return False
        if pid == os.getpid():
            return expected_start == self._process_start
        actual_start = _process_start_token(pid)
        return actual_start is not None and actual_start == expected_start

    def _read_state(self) -> tuple[dict, bool]:
        return self._state_store.read_clean(
            empty_state=self._empty_state,
            lease_is_alive=self._lease_is_alive,
            lease_max_age=self.lease_max_age,
        )

    def _write_state(self, state: dict) -> None:
        self._state_store.write(state)

    def _with_locked_state(self, action):
        with self._state_store.locked():
            state, cleanup_required = self._read_state()
            state_before_action = json.dumps(state, sort_keys=True)
            result = action(state)
            if (
                cleanup_required
                or json.dumps(state, sort_keys=True) != state_before_action
            ):
                self._write_state(state)
            return result

    @staticmethod
    def _counts(state: dict) -> dict[str, dict[str, int]]:
        return SchedulerPolicy.counts(state)

    @staticmethod
    def _is_constrained_local_descriptor(descriptor: str) -> bool:
        return SchedulerPolicy.is_constrained_local_descriptor(descriptor)

    @classmethod
    def _active_local_descriptors(cls, state: dict) -> set[str]:
        return SchedulerPolicy.active_local_descriptors(state)

    @staticmethod
    def _descriptor_lease_count(state: dict, descriptor: str) -> int:
        return SchedulerPolicy.descriptor_lease_count(state, descriptor)

    @staticmethod
    def _pending_requests(state: dict) -> list[dict]:
        return SchedulerPolicy.pending_requests(state)

    @staticmethod
    def _matches_affinity(request: dict, affinity: dict) -> bool:
        return SchedulerPolicy.matches_affinity(request, affinity)

    def _request_is_admissible(
        self,
        state: dict,
        request: dict,
    ) -> bool:
        return self._policy.is_admissible(state, request)

    def _format_counts(
        self,
        counts: dict[str, dict[str, int]],
        *,
        active_descriptors: set[str] | None = None,
    ) -> str:
        parts = [
            f"{descriptor} {values['running']} running, "
            f"{values['waiting']} waiting"
            for descriptor, values in sorted(counts.items())
        ]
        if active_descriptors is not None:
            parts.append(
                f"local resources {len(active_descriptors)}/"
                f"{self.ollama_max_loaded_models} active"
            )
        return " | ".join(parts)

    def _register_request(
        self,
        resource: str,
        descriptor: str,
        *,
        max_concurrent: int | None = None,
        budget_units: int = 0,
        affinity_key: str | None = None,
        kind: str = "operation",
        input_size: int = 0,
        cached_input_size: int = 0,
        parameters: dict[str, object] | None = None,
    ) -> tuple[SchedulerRequest, dict[str, dict[str, int]], set[str]]:
        request = SchedulerRequest(
            request_id=uuid.uuid4().hex,
            resource=resource,
            descriptor=descriptor,
            pid=os.getpid(),
            process_start=self._process_start,
            requested_at=time.time(),
            max_concurrent=max_concurrent or self.ollama_num_parallel,
            budget_units=budget_units,
            affinity_key=affinity_key,
            kind=kind,
            input_size=input_size,
            cached_input_size=cached_input_size,
            parameters=parameters,
        )

        def register(state):
            state["requests"][resource].append(asdict(request))
            return (
                request,
                self._counts(state),
                self._active_local_descriptors(state),
            )

        return self._with_locked_state(register)

    def _grant_available(self, state: dict) -> None:
        self._policy.grant_available(state)

    def _try_acquire(
        self,
        request: SchedulerRequest,
    ) -> tuple[
        SchedulerLease | None,
        dict[str, dict[str, int]] | None,
        set[str] | None,
    ]:
        resource = request.resource

        def acquire(state):
            leases = state["leases"]
            granted = next(
                (
                    item
                    for item in leases[resource]
                    if item.get("request_id") == request.request_id
                ),
                None,
            )
            if granted is None:
                self._grant_available(state)
                granted = next(
                    (
                        item
                        for item in leases[resource]
                        if item.get("request_id") == request.request_id
                    ),
                    None,
                )
            if granted is None:
                return None, None, None
            return (
                SchedulerLease(**granted),
                self._counts(state),
                self._active_local_descriptors(state),
            )

        return self._with_locked_state(acquire)

    def _remove_request(self, request: SchedulerRequest) -> None:
        def remove(state):
            self._policy.remove_request(
                state,
                resource=request.resource,
                request_id=request.request_id,
            )

        self._with_locked_state(remove)

    def _release(self, lease: SchedulerLease, *, succeeded: bool = True) -> None:
        def release(state):
            self._policy.release(
                state,
                resource=lease.resource,
                lease_id=lease.lease_id,
                request_id=lease.request_id,
                succeeded=succeeded,
            )

        self._with_locked_state(release)

    def _heartbeat(self, lease: SchedulerLease) -> bool:
        def heartbeat(state):
            return self._policy.heartbeat(
                state,
                resource=lease.resource,
                lease_id=lease.lease_id,
                now=time.time(),
            )

        return self._with_locked_state(heartbeat)

    async def _heartbeat_loop(self, lease: SchedulerLease) -> None:
        interval = max(0.01, self.lease_max_age / 3)
        while True:
            await asyncio.sleep(interval)
            if not await asyncio.to_thread(self._heartbeat, lease):
                return

    def snapshot(self) -> dict:
        """Return cleaned scheduler state for diagnostics and tests."""
        return self._with_locked_state(lambda state: state)

    @staticmethod
    def _descriptor_kind(descriptor: str) -> str:
        if descriptor == "docling":
            return "docling"
        if descriptor == "infinity" or descriptor.startswith("infinity/"):
            return "infinity"
        if descriptor.startswith("ollama/"):
            return "ollama"
        if descriptor.startswith("mlx/"):
            return "local"
        # LiteLLM cloud descriptors follow its provider/model convention.
        if "/" in descriptor:
            return "cloud"
        raise InfrastructureError(
            f"No scheduling policy is defined for descriptor {descriptor!r}",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="scheduler",
            operation="resolve_policy",
        )

    async def run(
        self,
        operation: Callable[..., T | Awaitable[T]],
        *,
        operation_kwargs: Mapping[str, object],
        wait_timeout: float | None = None,
    ) -> T:
        """Inspect and run one registered operation when capacity is ready."""
        if not callable(operation):
            raise TypeError("operation must be callable")
        kwargs = dict(operation_kwargs)
        profile = inspect_operation(operation, kwargs)
        descriptor = profile.descriptor.strip()
        input_size = profile.input_size
        kind = self._descriptor_kind(descriptor)
        if kind == "docling":
            resource = "docling"
            capacity = self.ollama_num_parallel
        elif kind in {"infinity", "ollama", "local"}:
            resource = "model"
            capacity = self.ollama_num_parallel
        else:
            resource = "model"
            # Cloud throughput is governed by the rolling token budget, not
            # by an unrelated local concurrency limit.
            capacity = 2**31 - 1

        budget_units = math.ceil(input_size / 3) if kind == "cloud" else 0
        logger.info(
            "Scheduling %s: descriptor=%s, input=%s, cached=%s, parameters=%s",
            profile.kind,
            descriptor,
            input_size,
            profile.cached_input_size,
            profile.parameters,
        )
        async with self.slot(
            resource,
            descriptor=descriptor,
            max_concurrent=capacity,
            timeout=wait_timeout,
            budget_units=budget_units,
            affinity_key=profile.affinity_key,
            kind=profile.kind,
            input_size=input_size,
            cached_input_size=profile.cached_input_size,
            parameters=profile.parameters,
        ):
            operation_started = time.monotonic()
            status = "failed"
            try:
                if inspect.iscoroutinefunction(operation):
                    result = await operation(**kwargs)
                else:
                    result = await asyncio.to_thread(operation, **kwargs)
                status = "completed"
                return result
            finally:
                logger.info(
                    "Scheduler job %s: kind=%s, descriptor=%s, runtime=%.3fs",
                    status,
                    profile.kind,
                    descriptor,
                    time.monotonic() - operation_started,
                )

    @asynccontextmanager
    async def slot(
        self,
        resource: str,
        *,
        max_concurrent: int | None = None,
        descriptor: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        budget_units: int = 0,
        affinity_key: str | None = None,
        kind: str = "operation",
        input_size: int = 0,
        cached_input_size: int = 0,
        parameters: dict[str, object] | None = None,
    ) -> AsyncGenerator[SchedulerLease, None]:
        if resource not in _RESOURCE_KEYS:
            raise ValueError(f"Unknown scheduler resource: {resource}")
        capacity = max_concurrent or self.ollama_num_parallel
        if capacity < 1:
            raise ValueError("max_concurrent must be at least 1")
        descriptor_key = descriptor or model or resource
        if (
            self._is_constrained_local_descriptor(descriptor_key)
            and self.ollama_max_loaded_models < 1
        ):
            raise ValueError("OLLAMA_MAX_LOADED_MODELS must be at least 1")
        if budget_units < 0:
            raise ValueError("budget_units cannot be negative")
        if affinity_key is not None:
            affinity_key = affinity_key.strip()
            if not affinity_key:
                raise ValueError("affinity_key cannot be empty")
        if (
            self.cloud_tpm_budget
            and budget_units > self.cloud_tpm_budget
        ):
            raise InfrastructureError(
                f"Request estimate ({budget_units}) exceeds "
                f"CLOUD_TPM_BUDGET ({self.cloud_tpm_budget})",
                kind=InfrastructureErrorKind.CONFIGURATION,
                provider="scheduler",
                operation="register_request",
            )
        wait_timeout = self.wait_timeout if timeout is None else timeout
        started = time.monotonic()
        request, counts, active_descriptors = await asyncio.to_thread(
            self._register_request,
            resource,
            descriptor_key,
            max_concurrent=capacity,
            budget_units=budget_units,
            affinity_key=affinity_key,
            kind=kind,
            input_size=input_size,
            cached_input_size=cached_input_size,
            parameters=parameters,
        )
        logger.info(
            "Scheduler request received: %s",
            self._format_counts(
                counts,
                active_descriptors=active_descriptors,
            ),
        )
        lease = None
        heartbeat_task: asyncio.Task[None] | None = None
        succeeded = False

        try:
            while True:
                lease, counts, active_descriptors = await asyncio.to_thread(
                    self._try_acquire,
                    request,
                )
                if lease is not None:
                    break
                elapsed = time.monotonic() - started
                if elapsed >= wait_timeout:
                    state = await asyncio.to_thread(self.snapshot)
                    occupancy = {
                        name: len(items)
                        for name, items in state["leases"].items()
                    }
                    raise SchedulingTimeoutError(
                        f"Timed out after {elapsed:.1f}s waiting for "
                        f"{descriptor_key}; active leases: {occupancy}"
                    )
                await asyncio.sleep(self.poll_interval)

            if counts is not None:
                logger.info(
                    "Scheduler job started: %s",
                    self._format_counts(
                        counts,
                        active_descriptors=active_descriptors,
                    ),
                )
            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(lease)
            )
            yield lease
            succeeded = True
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            if lease is None:
                await asyncio.to_thread(self._remove_request, request)
            else:
                await asyncio.to_thread(
                    self._release,
                    lease,
                    succeeded=succeeded,
                )


class _DefaultScheduler:
    """Delay environment and path resolution until the first scheduled job."""

    def __init__(self) -> None:
        self._instance: Scheduler | None = None

    def _get(self) -> Scheduler:
        if self._instance is None:
            self._instance = Scheduler()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get(), name)


# Independent CLI processes each create one local coordinator on first use.
scheduler = _DefaultScheduler()
