"""Typed, provider-neutral telemetry records used by the detection engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FlowVerdict = Literal["forwarded", "dropped", "audit", "unknown"]
IdentityStatus = Literal["resolved", "unmapped"]


@dataclass(frozen=True)
class WorkloadIdentity:
    tenant_id: str
    workload_id: str
    workload_name: str


@dataclass(frozen=True)
class NormalizedFlow:
    event_id: str
    observed_at: float
    source: WorkloadIdentity | None
    destination: WorkloadIdentity | None
    identity_status: IdentityStatus
    verdict: FlowVerdict
    drop_reason: str | None
    protocol: str | None
    destination_port: int | None
    node_name: str | None

    @property
    def cross_tenant(self) -> bool | None:
        if not self.source or not self.destination:
            return None
        return self.source.tenant_id != self.destination.tenant_id

    @property
    def policy_denied(self) -> bool:
        return self.verdict == "dropped" and self.drop_reason == "POLICY_DENIED"
