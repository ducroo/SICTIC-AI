from __future__ import annotations

import asyncio
import fcntl
import json
import os
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from lib.logger import get_logger

logger = get_logger(__name__)

_RESOURCE_KEYS = ("docling", "embedding", "llm", "rerank")
_DEFAULT_WAIT_TIMEOUT = 3600.0
_POLL_INTERVAL = 0.05
# A lease held longer than this is treated as leaked and reclaimed even if
# the owning process is still alive: a hung provider call never returns, so
# pid-liveness alone cannot distinguish a stuck job from a long one.
_DEFAULT_LEASE_MAX_AGE = 1800.0
_DEFAULT_LLM_REQUEST_TIMEOUT = 600.0
_DEFAULT_EMBEDDING_REQUEST_TIMEOUT = 300.0
_DEFAULT_RERANK_REQUEST_TIMEOUT = 120.0


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r", name, raw)
        return default


class GatewayTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class ServiceLease:
    lease_id: str
    request_id: str
    resource: str
    model: str
    pid: int
    process_start: str
    acquired_at: float


@dataclass(frozen=True)
class ServiceRequest:
    request_id: str
    resource: str
    model: str
    pid: int
    process_start: str
    requested_at: float
    max_concurrent: int


def default_gateway_state_path() -> Path:
    """Return the gateway state path under the repository-local cache."""
    local_data_root = (
        os.environ.get("LOCAL_DATA_PATH")
        or os.environ.get("REPO_PATH")
        or Path(__file__).resolve().parents[1]
    )
    return (
        Path(local_data_root).expanduser().resolve()
        / "cache"
        / "services-gateway.json"
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


class ServicesGateway:
    """Coordinate local service capacity across independent CLI processes."""

    def __init__(
        self,
        *,
        state_path: str | os.PathLike | None = None,
        ollama_num_parallel: int | None = None,
        ollama_max_loaded_models: int | None = None,
        wait_timeout: float = _DEFAULT_WAIT_TIMEOUT,
        poll_interval: float = _POLL_INTERVAL,
        lease_max_age: float | None = None,
    ):
        self.state_path = Path(
            state_path or default_gateway_state_path()
        ).expanduser()
        self.ollama_num_parallel = (
            ollama_num_parallel
            if ollama_num_parallel is not None
            else int(os.environ.get("OLLAMA_NUM_PARALLEL", "1"))
        )
        self.ollama_max_loaded_models = (
            ollama_max_loaded_models
            if ollama_max_loaded_models is not None
            else int(os.environ.get("OLLAMA_MAX_LOADED_MODELS", "1"))
        )
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.lease_max_age = (
            lease_max_age
            if lease_max_age is not None
            else _float_env("GATEWAY_LEASE_MAX_AGE", _DEFAULT_LEASE_MAX_AGE)
        )
        self._process_start = _process_start_token(os.getpid()) or str(
            time.time_ns()
        )

    def _empty_state(self) -> dict:
        return {
            "version": 5,
            "leases": {resource: [] for resource in _RESOURCE_KEYS},
            "requests": {resource: [] for resource in _RESOURCE_KEYS},
        }

    def _ensure_parent(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

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

    def _read_state(self, handle) -> tuple[dict, bool]:
        handle.seek(0)
        content = handle.read()
        if not content:
            return self._empty_state(), False
        try:
            state = json.loads(content)
        except (TypeError, json.JSONDecodeError) as error:
            logger.warning(
                "Resetting invalid services gateway state at %s: %s",
                self.state_path,
                error,
            )
            return self._empty_state(), True

        leases = state.get("leases")
        requests = state.get("requests", {})
        if not isinstance(leases, dict) or not isinstance(requests, dict):
            return self._empty_state(), True
        cleaned = self._empty_state()
        process_alive: dict[tuple[int, str], bool] = {}
        now = time.time()

        def lease_is_current(lease: dict) -> bool:
            try:
                age = now - float(lease["acquired_at"])
            except (KeyError, TypeError, ValueError):
                return False
            if age <= self.lease_max_age:
                return True
            logger.warning(
                "Reclaiming expired %s lease held by pid %s "
                "(age %.0fs > max %.0fs)",
                lease.get("resource"),
                lease.get("pid"),
                age,
                self.lease_max_age,
            )
            return False

        def entry_is_alive(entry: dict) -> bool:
            try:
                identity = (
                    int(entry["pid"]),
                    str(entry["process_start"]),
                )
            except (KeyError, TypeError, ValueError):
                return False
            if identity not in process_alive:
                process_alive[identity] = self._lease_is_alive(entry)
            return process_alive[identity]

        for resource in _RESOURCE_KEYS:
            pool = leases.get(resource, [])
            if isinstance(pool, list):
                cleaned["leases"][resource] = [
                    lease
                    for lease in pool
                    if isinstance(lease, dict)
                    and entry_is_alive(lease)
                    and lease_is_current(lease)
                ]
            queue = requests.get(resource, [])
            if isinstance(queue, list):
                cleaned["requests"][resource] = [
                    request
                    for request in queue
                    if isinstance(request, dict)
                    and entry_is_alive(request)
                ]
        return cleaned, cleaned != state

    def _write_state(self, handle, state: dict) -> None:
        handle.seek(0)
        handle.truncate()
        json.dump(state, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())

    def _with_locked_state(self, action):
        self._ensure_parent()
        with self.state_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                state, cleanup_required = self._read_state(handle)
                state_before_action = json.dumps(state, sort_keys=True)
                result = action(state)
                if (
                    cleanup_required
                    or json.dumps(state, sort_keys=True) != state_before_action
                ):
                    self._write_state(handle, state)
                return result
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _counts(state: dict) -> dict[str, dict[str, int]]:
        return {
            resource: {
                "running": len(state["leases"][resource]),
                "waiting": len(state["requests"][resource]),
            }
            for resource in _RESOURCE_KEYS
        }

    @staticmethod
    def _active_models(state: dict) -> set[str]:
        models: set[str] = set()
        for leases in state["leases"].values():
            models.update(
                str(lease.get("model") or lease.get("resource"))
                for lease in leases
            )
        return models

    @staticmethod
    def _model_lease_count(state: dict, model: str) -> int:
        return sum(
            1
            for leases in state["leases"].values()
            for lease in leases
            if str(lease.get("model") or lease.get("resource")) == model
        )

    @staticmethod
    def _pending_requests(state: dict) -> list[dict]:
        pending = [
            request
            for queue in state["requests"].values()
            for request in queue
        ]
        return sorted(pending, key=lambda item: item.get("requested_at", 0))

    def _request_is_admissible(
        self,
        state: dict,
        request: dict,
    ) -> bool:
        model = str(request.get("model") or request.get("resource"))
        active_models = self._active_models(state)
        model_already_loaded = model in active_models
        if (
            not model_already_loaded
            and len(active_models) >= self.ollama_max_loaded_models
        ):
            return False
        capacity = int(
            request.get("max_concurrent") or self.ollama_num_parallel
        )
        return self._model_lease_count(state, model) < capacity

    def _format_counts(
        self,
        counts: dict[str, dict[str, int]],
        *,
        active_models: set[str] | None = None,
    ) -> str:
        labels = {
            "docling": "docling",
            "embedding": "embedding",
            "llm": "LLM",
            "rerank": "rerank",
        }
        summary = " | ".join(
            f"{labels[resource]} {counts[resource]['running']} running, "
            f"{counts[resource]['waiting']} waiting"
            for resource in ("llm", "embedding", "rerank", "docling")
        )
        if active_models is not None:
            summary = (
                f"{summary} | models {len(active_models)}/"
                f"{self.ollama_max_loaded_models} loaded"
            )
        return summary

    def _register_request(
        self,
        resource: str,
        model: str,
        *,
        max_concurrent: int | None = None,
    ) -> tuple[ServiceRequest, dict[str, dict[str, int]], set[str]]:
        request = ServiceRequest(
            request_id=uuid.uuid4().hex,
            resource=resource,
            model=model,
            pid=os.getpid(),
            process_start=self._process_start,
            requested_at=time.time(),
            max_concurrent=max_concurrent or self.ollama_num_parallel,
        )

        def register(state):
            state["requests"][resource].append(asdict(request))
            return request, self._counts(state), self._active_models(state)

        return self._with_locked_state(register)

    def _grant_available(self, state: dict) -> None:
        """Grant every currently available slot in global FIFO order."""
        while True:
            request = next(
                (
                    item
                    for item in self._pending_requests(state)
                    if self._request_is_admissible(state, item)
                ),
                None,
            )
            if request is None:
                return
            resource = str(request["resource"])
            request_id = str(request["request_id"])
            state["requests"][resource] = [
                item
                for item in state["requests"][resource]
                if item.get("request_id") != request_id
            ]
            state["leases"][resource].append(
                asdict(
                    ServiceLease(
                        lease_id=uuid.uuid4().hex,
                        request_id=request_id,
                        resource=resource,
                        model=str(request.get("model") or resource),
                        pid=int(request["pid"]),
                        process_start=str(request["process_start"]),
                        acquired_at=time.time(),
                    )
                )
            )

    def _try_acquire(
        self,
        request: ServiceRequest,
        *,
        max_concurrent: int,
    ) -> tuple[
        ServiceLease | None,
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
                ServiceLease(**granted),
                self._counts(state),
                self._active_models(state),
            )

        return self._with_locked_state(acquire)

    def _remove_request(self, request: ServiceRequest) -> None:
        def remove(state):
            queue = state["requests"][request.resource]
            state["requests"][request.resource] = [
                item
                for item in queue
                if item.get("request_id") != request.request_id
            ]
            state["leases"][request.resource] = [
                item
                for item in state["leases"][request.resource]
                if item.get("request_id") != request.request_id
            ]

        self._with_locked_state(remove)

    def _release(self, lease: ServiceLease) -> None:
        def release(state):
            pool = state["leases"][lease.resource]
            state["leases"][lease.resource] = [
                item
                for item in pool
                if item.get("lease_id") != lease.lease_id
            ]

        self._with_locked_state(release)

    def snapshot(self) -> dict:
        """Return cleaned gateway state for diagnostics and tests."""
        return self._with_locked_state(lambda state: state)

    @asynccontextmanager
    async def slot(
        self,
        resource: str,
        *,
        max_concurrent: int | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[ServiceLease]:
        if resource not in _RESOURCE_KEYS:
            raise ValueError(f"Unknown gateway resource: {resource}")
        capacity = max_concurrent or self.ollama_num_parallel
        if capacity < 1:
            raise ValueError("max_concurrent must be at least 1")
        if self.ollama_max_loaded_models < 1:
            raise ValueError("OLLAMA_MAX_LOADED_MODELS must be at least 1")
        model_key = model or resource
        wait_timeout = self.wait_timeout if timeout is None else timeout
        started = time.monotonic()
        request, counts, active_models = await asyncio.to_thread(
            self._register_request,
            resource,
            model_key,
            max_concurrent=capacity,
        )
        logger.info(
            "Gateway request received: %s",
            self._format_counts(counts, active_models=active_models),
        )
        lease = None

        try:
            while True:
                lease, counts, active_models = await asyncio.to_thread(
                    self._try_acquire,
                    request,
                    max_concurrent=capacity,
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
                    raise GatewayTimeoutError(
                        f"Timed out after {elapsed:.1f}s waiting for "
                        f"{resource}; active leases: {occupancy}"
                    )
                await asyncio.sleep(self.poll_interval)

            if counts is not None:
                logger.info(
                    "Gateway job started: %s",
                    self._format_counts(counts, active_models=active_models),
                )
            yield lease
        finally:
            if lease is None:
                await asyncio.to_thread(self._remove_request, request)
            else:
                await asyncio.to_thread(self._release, lease)

    async def request_embedding(
        self,
        kwargs: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        """Coordinate embeddings by model slots and per-model parallelism."""
        import litellm

        litellm.disable_aiohttp_transport = True
        # Bound the provider call so a hung connection raises and releases
        # its lease instead of blocking the machine-wide slot forever.
        kwargs.setdefault(
            "timeout",
            _float_env(
                "EMBEDDING_REQUEST_TIMEOUT",
                _DEFAULT_EMBEDDING_REQUEST_TIMEOUT,
            ),
        )
        async with self.slot(
            "embedding",
            model=str(kwargs.get("model") or "embedding"),
            timeout=timeout,
        ):
            return await litellm.aembedding(**kwargs)

    async def request_completion(
        self,
        kwargs: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        """Coordinate completions by model slots and per-model parallelism."""
        import litellm

        litellm.disable_aiohttp_transport = True
        # Bound the provider call so a hung connection raises and releases
        # its lease instead of blocking the machine-wide slot forever.
        kwargs.setdefault(
            "timeout",
            _float_env(
                "LLM_REQUEST_TIMEOUT",
                _DEFAULT_LLM_REQUEST_TIMEOUT,
            ),
        )
        async with self.slot(
            "llm",
            model=str(kwargs.get("model") or "llm"),
            timeout=timeout,
        ):
            return await litellm.acompletion(**kwargs)

    async def request_rerank(
        self,
        kwargs: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        """Coordinate reranking by model slots and per-model parallelism."""
        import litellm

        litellm.disable_aiohttp_transport = True
        kwargs.setdefault(
            "timeout",
            _float_env(
                "RERANK_REQUEST_TIMEOUT",
                _DEFAULT_RERANK_REQUEST_TIMEOUT,
            ),
        )
        async with self.slot(
            "rerank",
            model=str(kwargs.get("model") or "rerank"),
            timeout=timeout,
        ):
            return await litellm.arerank(**kwargs)


class _DefaultGateway:
    """Delay environment and path resolution until the first gateway call."""

    def __init__(self):
        self._instance: ServicesGateway | None = None

    def _get(self) -> ServicesGateway:
        if self._instance is None:
            self._instance = ServicesGateway()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get(), name)


# Independent CLI processes each create one local coordinator on first use.
gateway = _DefaultGateway()
