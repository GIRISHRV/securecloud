"""Typed boundary between management intent and infrastructure state."""

from dataclasses import dataclass
from typing import Mapping, Protocol


class InfrastructureError(RuntimeError):
    """An infrastructure operation failed conclusively."""


class InfrastructurePending(InfrastructureError):
    """The requested state has not been observed yet."""

    def __init__(
        self,
        message: str,
        observation: "WorkloadObservation | StackObservation | None" = None,
    ):
        super().__init__(message)
        self.observation = observation


class InfrastructureUnavailable(InfrastructureError):
    """The infrastructure state cannot currently be observed."""


class InfrastructureConflict(InfrastructureError):
    """The resource changed after SecureCloud last observed it."""


@dataclass(frozen=True)
class WorkloadRequest:
    id: str
    tenant_id: str
    name: str
    template: str
    kubernetes_uid: str | None = None
    kubernetes_version: str | None = None

    @classmethod
    def from_mapping(cls, row: Mapping) -> "WorkloadRequest":
        return cls(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            template=row["template"],
            kubernetes_uid=row["kubernetes_uid"],
            kubernetes_version=row["kubernetes_version"],
        )


@dataclass(frozen=True)
class WorkloadObservation:
    state: str
    uid: str | None
    resource_version: str | None


@dataclass(frozen=True)
class StackRequest:
    id: str
    tenant_id: str
    name: str
    stack_id: str

    @classmethod
    def from_mapping(cls, row: Mapping) -> "StackRequest":
        return cls(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            stack_id=row["stack_id"],
        )


@dataclass(frozen=True)
class StackObservation:
    state: str
    components: Mapping[str, WorkloadObservation]


@dataclass(frozen=True)
class ContainmentObservation:
    state: str
    policy_uid: str | None
    resource_version: str | None


class InfrastructureAdapter(Protocol):
    def health(self) -> dict: ...

    def reconcile(self, action: str, workload: WorkloadRequest) -> WorkloadObservation: ...

    def reconcile_stack(
        self,
        action: str,
        stack: StackRequest,
        components: Mapping[str, WorkloadRequest],
    ) -> StackObservation: ...

    def reconcile_quarantine(
        self, workload: WorkloadRequest, enabled: bool
    ) -> ContainmentObservation: ...
