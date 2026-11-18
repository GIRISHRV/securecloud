"""Deterministic adapter used by unit tests, never as deployment evidence."""

from dataclasses import replace

from .base import (
    ContainmentObservation,
    InfrastructureConflict,
    StackObservation,
    StackRequest,
    WorkloadObservation,
    WorkloadRequest,
)


class MemoryInfrastructure:
    def __init__(self):
        self.workloads: dict[str, WorkloadObservation] = {}
        self.quarantined: set[str] = set()

    def health(self) -> dict:
        return {"connected": True, "provider": "memory-test-double"}

    def reconcile(self, action: str, workload: WorkloadRequest) -> WorkloadObservation:
        current = self.workloads.get(workload.id)
        if action == "deploy":
            version = str(int(current.resource_version) + 1) if current else "1"
            result = WorkloadObservation("running", current.uid if current else f"test-{workload.id}", version)
            self.workloads[workload.id] = result
            return result
        if current is None:
            raise InfrastructureConflict("Workload does not exist")
        if workload.kubernetes_uid and workload.kubernetes_uid != current.uid:
            raise InfrastructureConflict("Workload UID changed")
        if workload.kubernetes_version and workload.kubernetes_version != current.resource_version:
            raise InfrastructureConflict("Workload resource version changed")
        if action == "stop":
            result = replace(current, state="stopped", resource_version=str(int(current.resource_version) + 1))
            self.workloads[workload.id] = result
            return result
        if action == "delete":
            del self.workloads[workload.id]
            return WorkloadObservation("deleted", None, None)
        raise ValueError(f"Unsupported action: {action}")

    def reconcile_quarantine(
        self, workload: WorkloadRequest, enabled: bool
    ) -> ContainmentObservation:
        if enabled:
            self.quarantined.add(workload.id)
            return ContainmentObservation("quarantined", f"test-policy-{workload.id}", "1")
        self.quarantined.discard(workload.id)
        return ContainmentObservation("restored", None, None)
    StackObservation,
    StackRequest,

    def reconcile_stack(
        self,
        action: str,
        stack: StackRequest,
        components: dict[str, WorkloadRequest],
    ) -> StackObservation:
        if action != "deploy":
            raise ValueError(f"Unsupported stack action: {action}")
        observations = {
            name: self.reconcile("deploy", workload)
            for name, workload in components.items()
        }
        return StackObservation("running", observations)
