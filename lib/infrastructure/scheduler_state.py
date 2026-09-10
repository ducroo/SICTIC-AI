"""Crash-safe file storage for the cross-process scheduler state."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from lib.infrastructure.logging import get_logger


logger = get_logger(__name__)

_CLOUD_BUDGET_WINDOW_SECONDS = 60.0


class SchedulerStateStore:
    """Serialize scheduler transactions behind a dedicated file lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_name(f"{path.name}.lock")

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def read(self) -> tuple[Any | None, bool]:
        """Return decoded state and whether corrupt data was encountered."""
        if not self.path.exists():
            return None, False
        content = self.path.read_text(encoding="utf-8")
        if not content:
            return None, False
        try:
            return json.loads(content), False
        except (TypeError, json.JSONDecodeError):
            return None, True

    def read_clean(
        self,
        *,
        empty_state: Callable[[], dict],
        lease_is_alive: Callable[[dict], bool],
        lease_max_age: float,
    ) -> tuple[dict, bool]:
        """Decode, migrate, and remove stale entries from persisted state."""
        state, corrupt = self.read()
        if state is None and not corrupt:
            return empty_state(), False
        if corrupt or not isinstance(state, dict):
            logger.warning("Resetting invalid scheduler state at %s", self.path)
            return empty_state(), True

        leases = state.get("leases")
        requests = state.get("requests", {})
        if not isinstance(leases, dict) or not isinstance(requests, dict):
            return empty_state(), True

        cleaned = empty_state()
        process_alive: dict[tuple[int, str], bool] = {}
        now = time.time()

        def entry_is_alive(entry: dict) -> bool:
            try:
                identity = (int(entry["pid"]), str(entry["process_start"]))
            except (KeyError, TypeError, ValueError):
                return False
            if identity not in process_alive:
                process_alive[identity] = lease_is_alive(entry)
            return process_alive[identity]

        def lease_is_current(lease: dict) -> bool:
            try:
                last_seen = lease.get("heartbeat_at", lease["acquired_at"])
                age = now - float(last_seen)
            except (KeyError, TypeError, ValueError):
                return False
            if age <= lease_max_age:
                return True
            logger.warning(
                "Reclaiming expired %s lease held by pid %s "
                "(age %.0fs > max %.0fs)",
                lease.get("resource"),
                lease.get("pid"),
                age,
                lease_max_age,
            )
            return False

        def normalized_entry(entry: dict) -> dict:
            normalized = dict(entry)
            if "descriptor" not in normalized and "model" in normalized:
                normalized["descriptor"] = normalized.pop("model")
            if (
                "lease_id" in normalized
                and "heartbeat_at" not in normalized
                and "acquired_at" in normalized
            ):
                normalized["heartbeat_at"] = normalized["acquired_at"]
            return normalized

        for resource in cleaned["leases"]:
            pool = leases.get(resource, [])
            if isinstance(pool, list):
                cleaned["leases"][resource] = [
                    normalized_entry(lease)
                    for lease in pool
                    if isinstance(lease, dict)
                    and entry_is_alive(lease)
                    and lease_is_current(lease)
                ]
            queue = requests.get(resource, [])
            if isinstance(queue, list):
                cleaned["requests"][resource] = [
                    normalized_entry(request)
                    for request in queue
                    if isinstance(request, dict)
                    and entry_is_alive(request)
                ]

        cleaned["cloud_usage"] = self._clean_cloud_usage(
            state.get("cloud_usage"),
            now=now,
        )
        cleaned["exclusive_affinity"] = self._clean_affinity(
            state.get("exclusive_affinity"),
            cleaned,
        )
        return cleaned, cleaned != state

    @staticmethod
    def _clean_cloud_usage(value: Any, *, now: float) -> list[dict]:
        if not isinstance(value, list):
            return []
        cutoff = now - _CLOUD_BUDGET_WINDOW_SECONDS
        usage = []
        for item in value:
            if not isinstance(item, dict):
                continue
            try:
                request_time = float(item["request_time"])
                units = int(item["units"])
            except (KeyError, TypeError, ValueError):
                continue
            if request_time > cutoff and units > 0:
                usage.append({"request_time": request_time, "units": units})
        return sorted(usage, key=lambda item: item["request_time"])

    @staticmethod
    def _clean_affinity(value: Any, state: dict) -> dict | None:
        if not isinstance(value, dict):
            return None
        affinity = {
            "descriptor": value.get("descriptor"),
            "affinity_key": value.get("affinity_key"),
            "phase": value.get("phase"),
            "request_id": value.get("request_id"),
        }
        descriptor = affinity["descriptor"]
        affinity_key = affinity["affinity_key"]
        if not (
            isinstance(descriptor, str)
            and descriptor
            and isinstance(affinity_key, str)
            and affinity_key
        ):
            return None

        pending = [
            request
            for queue in state["requests"].values()
            for request in queue
        ]
        leases = [
            lease for pool in state["leases"].values() for lease in pool
        ]
        if affinity["phase"] == "warming":
            request_id = affinity["request_id"]
            if isinstance(request_id, str) and any(
                lease.get("request_id") == request_id for lease in leases
            ):
                return affinity
        if affinity["phase"] == "draining" and any(
            request.get("descriptor") == descriptor
            and request.get("affinity_key") == affinity_key
            for request in pending
        ):
            return affinity
        return None

    def write(self, state: dict) -> None:
        """Atomically replace the state while callers hold ``locked()``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary_path.unlink(missing_ok=True)
