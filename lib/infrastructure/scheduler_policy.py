"""Pure admission and queue transitions for infrastructure scheduling."""

from __future__ import annotations

import time
import uuid


_CLOUD_BUDGET_WINDOW_SECONDS = 60.0


class SchedulerPolicy:
    """Apply capacity, budget, and affinity rules to scheduler state."""

    def __init__(
        self,
        *,
        default_capacity: int,
        max_loaded_models: int,
        cloud_tpm_budget: int,
    ) -> None:
        self.default_capacity = default_capacity
        self.max_loaded_models = max_loaded_models
        self.cloud_tpm_budget = cloud_tpm_budget

    @staticmethod
    def counts(state: dict) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for state_key, count_key in (
            ("leases", "running"),
            ("requests", "waiting"),
        ):
            for resource, entries in state[state_key].items():
                for entry in entries:
                    descriptor = SchedulerPolicy.descriptor(entry, resource)
                    values = counts.setdefault(
                        descriptor,
                        {"running": 0, "waiting": 0},
                    )
                    values[count_key] += 1
        return counts

    @staticmethod
    def descriptor(entry: dict, fallback: str = "") -> str:
        return str(
            entry.get("descriptor")
            or entry.get("model")
            or entry.get("resource")
            or fallback
        )

    @staticmethod
    def is_constrained_local_descriptor(descriptor: str) -> bool:
        return (
            descriptor == "docling"
            or descriptor == "infinity"
            or descriptor.startswith(("ollama/", "infinity/"))
        )

    @classmethod
    def active_local_descriptors(cls, state: dict) -> set[str]:
        return {
            descriptor
            for leases in state["leases"].values()
            for lease in leases
            if cls.is_constrained_local_descriptor(
                descriptor := cls.descriptor(lease)
            )
        }

    @classmethod
    def descriptor_lease_count(cls, state: dict, descriptor: str) -> int:
        return sum(
            cls.descriptor(lease) == descriptor
            for leases in state["leases"].values()
            for lease in leases
        )

    @staticmethod
    def pending_requests(state: dict) -> list[dict]:
        pending = [
            request
            for queue in state["requests"].values()
            for request in queue
        ]
        return sorted(pending, key=lambda item: item.get("requested_at", 0))

    @staticmethod
    def matches_affinity(request: dict, affinity: dict) -> bool:
        return (
            request.get("descriptor") == affinity.get("descriptor")
            and request.get("affinity_key") == affinity.get("affinity_key")
        )

    def is_admissible(self, state: dict, request: dict) -> bool:
        descriptor = self.descriptor(request)
        if self.is_constrained_local_descriptor(descriptor):
            active = self.active_local_descriptors(state)
            if descriptor not in active and len(active) >= self.max_loaded_models:
                return False

        capacity = int(request.get("max_concurrent") or self.default_capacity)
        if self.descriptor_lease_count(state, descriptor) >= capacity:
            return False

        budget_units = int(request.get("budget_units") or 0)
        if not budget_units or not self.cloud_tpm_budget:
            return True
        used = sum(int(item["units"]) for item in state["cloud_usage"])
        return used + budget_units <= self.cloud_tpm_budget

    def grant_available(self, state: dict) -> None:
        """Grant capacity in queue order, skipping inadmissible requests."""
        while True:
            now = time.time()
            cutoff = now - _CLOUD_BUDGET_WINDOW_SECONDS
            state["cloud_usage"] = [
                item
                for item in state["cloud_usage"]
                if float(item["request_time"]) > cutoff
            ]
            pending = self.pending_requests(state)
            affinity = state["exclusive_affinity"]
            if affinity is not None:
                if affinity["phase"] == "warming":
                    return
                candidates = [
                    request
                    for request in pending
                    if self.matches_affinity(request, affinity)
                ]
                if not candidates:
                    state["exclusive_affinity"] = None
                    continue
            else:
                candidates = pending

            request = next(
                (
                    candidate
                    for candidate in candidates
                    if self.is_admissible(state, candidate)
                ),
                None,
            )
            if request is None:
                return

            affinity_key = request.get("affinity_key")
            starts_affinity = affinity is None and bool(affinity_key)
            if starts_affinity:
                state["exclusive_affinity"] = {
                    "descriptor": request["descriptor"],
                    "affinity_key": affinity_key,
                    "phase": "warming",
                    "request_id": request["request_id"],
                }

            resource = str(request["resource"])
            request_id = str(request["request_id"])
            state["requests"][resource] = [
                item
                for item in state["requests"][resource]
                if item.get("request_id") != request_id
            ]
            state["leases"][resource].append(
                {
                    "lease_id": uuid.uuid4().hex,
                    "request_id": request_id,
                    "resource": resource,
                    "descriptor": self.descriptor(request, resource),
                    "pid": int(request["pid"]),
                    "process_start": str(request["process_start"]),
                    "acquired_at": now,
                    "heartbeat_at": now,
                    "affinity_key": affinity_key,
                    "kind": request.get("kind", "operation"),
                    "input_size": int(request.get("input_size") or 0),
                    "cached_input_size": int(
                        request.get("cached_input_size") or 0
                    ),
                    "parameters": request.get("parameters"),
                }
            )
            budget_units = int(request.get("budget_units") or 0)
            if budget_units:
                state["cloud_usage"].append(
                    {"request_time": now, "units": budget_units}
                )
            if starts_affinity:
                return

    @staticmethod
    def remove_request(state: dict, *, resource: str, request_id: str) -> None:
        state["requests"][resource] = [
            item
            for item in state["requests"][resource]
            if item.get("request_id") != request_id
        ]
        state["leases"][resource] = [
            item
            for item in state["leases"][resource]
            if item.get("request_id") != request_id
        ]

    def release(
        self,
        state: dict,
        *,
        resource: str,
        lease_id: str,
        request_id: str,
        succeeded: bool,
    ) -> None:
        state["leases"][resource] = [
            item
            for item in state["leases"][resource]
            if item.get("lease_id") != lease_id
        ]
        affinity = state["exclusive_affinity"]
        owns_warmup = (
            affinity is not None
            and affinity.get("phase") == "warming"
            and affinity.get("request_id") == request_id
        )
        if not owns_warmup:
            return
        if not succeeded:
            state["exclusive_affinity"] = None
            return

        affinity["phase"] = "draining"
        if not any(
            self.matches_affinity(request, affinity)
            for request in self.pending_requests(state)
        ):
            state["exclusive_affinity"] = None

    @staticmethod
    def heartbeat(
        state: dict,
        *,
        resource: str,
        lease_id: str,
        now: float,
    ) -> bool:
        for item in state["leases"][resource]:
            if item.get("lease_id") == lease_id:
                item["heartbeat_at"] = now
                return True
        return False
