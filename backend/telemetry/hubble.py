"""Normalize Hubble JSON flow-export records without inferring missing identity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from backend.infrastructure.kubernetes import tenant_namespace

from .schema import NormalizedFlow, WorkloadIdentity


class HubbleNormalizationError(ValueError):
    """The record is malformed and cannot be retained as a flow."""


@dataclass(frozen=True)
class EndpointReference:
    namespace: str
    pod_name: str | None
    workload_name: str | None


class IdentityIndex:
    """Resolve Hubble endpoint metadata to stable SecureCloud database IDs."""

    def __init__(self, identities: Iterable[WorkloadIdentity]):
        self._by_workload: dict[tuple[str, str], WorkloadIdentity] = {}
        for identity in identities:
            key = (tenant_namespace(identity.tenant_id), identity.workload_name)
            if key in self._by_workload:
                raise ValueError("Duplicate workload identity mapping")
            self._by_workload[key] = identity

    def resolve(self, endpoint: EndpointReference) -> WorkloadIdentity | None:
        if endpoint.workload_name:
            identity = self._by_workload.get(
                (endpoint.namespace, endpoint.workload_name),
            )
            if identity:
                return identity
        if endpoint.pod_name:
            candidates = [
                identity
                for (namespace, name), identity in self._by_workload.items()
                if namespace == endpoint.namespace
                and endpoint.pod_name.startswith(f"{name}-")
            ]
            if len(candidates) == 1:
                return candidates[0]
        return None


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HubbleNormalizationError(f"{field} must be an object")
    return value


def _timestamp(value: Any) -> float:
    if not isinstance(value, str) or not value:
        raise HubbleNormalizationError("time must be an RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HubbleNormalizationError("time is not valid RFC3339") from exc
    if parsed.tzinfo is None:
        raise HubbleNormalizationError("time must include a timezone")
    return parsed.astimezone(timezone.utc).timestamp()


def _endpoint(value: Any, field: str) -> EndpointReference:
    endpoint = _mapping(value, field)
    namespace = endpoint.get("namespace")
    if not isinstance(namespace, str) or not namespace:
        return EndpointReference("", None, None)
    pod_name = endpoint.get("pod_name")
    if not isinstance(pod_name, str) or not pod_name:
        pod_name = None
    workload_name = None
    workloads = endpoint.get("workloads")
    if isinstance(workloads, list) and workloads:
        workload = workloads[0]
        if isinstance(workload, Mapping) and isinstance(workload.get("name"), str):
            workload_name = workload["name"] or None
    return EndpointReference(namespace, pod_name, workload_name)


def _layer4(value: Any) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    layer4 = _mapping(value, "l4")
    for protocol_name in ("TCP", "UDP", "SCTP"):
        protocol = layer4.get(protocol_name)
        if protocol is None:
            protocol = layer4.get(protocol_name.lower())
        if not isinstance(protocol, Mapping):
            continue
        port = protocol.get("destination_port")
        if port is None:
            return protocol_name.lower(), None
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise HubbleNormalizationError("destination port is invalid")
        return protocol_name.lower(), port
    return None, None


def normalize_hubble_flow(
    payload: Mapping[str, Any],
    identities: IdentityIndex,
) -> NormalizedFlow:
    """Normalize a direct exporter Flow or an observer response containing `flow`."""
    container = _mapping(payload, "record")
    flow = container.get("flow", container)
    flow = _mapping(flow, "flow")
    observed_at = _timestamp(flow.get("time"))
    source_ref = _endpoint(flow.get("source", {}), "source")
    destination_ref = _endpoint(flow.get("destination", {}), "destination")
    source = identities.resolve(source_ref)
    destination = identities.resolve(destination_ref)
    protocol, destination_port = _layer4(flow.get("l4"))

    raw_verdict = flow.get("verdict")
    verdicts = {
        "FORWARDED": "forwarded",
        "DROPPED": "dropped",
        "AUDIT": "audit",
    }
    verdict = verdicts.get(raw_verdict, "unknown")
    raw_drop_reason = flow.get("drop_reason_desc")
    drop_reason = raw_drop_reason if isinstance(raw_drop_reason, str) else None
    raw_uuid = flow.get("uuid")
    if isinstance(raw_uuid, str) and raw_uuid:
        event_id = raw_uuid
    else:
        canonical = json.dumps(flow, sort_keys=True, separators=(",", ":"))
        event_id = f"hubble-{sha256(canonical.encode()).hexdigest()}"
    node_name = flow.get("node_name")
    if not isinstance(node_name, str) or not node_name:
        node_name = None

    return NormalizedFlow(
        event_id=event_id,
        observed_at=observed_at,
        source=source,
        destination=destination,
        identity_status="resolved" if source and destination else "unmapped",
        verdict=verdict,
        drop_reason=drop_reason,
        protocol=protocol,
        destination_port=destination_port,
        node_name=node_name,
        is_reply=flow.get("is_reply") is True,
    )


def normalize_hubble_json_line(
    line: str,
    identities: IdentityIndex,
    *,
    max_bytes: int = 1_048_576,
) -> NormalizedFlow:
    if len(line.encode("utf-8")) > max_bytes:
        raise HubbleNormalizationError("flow record exceeds the size limit")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise HubbleNormalizationError("flow record is not valid JSON") from exc
    return normalize_hubble_flow(payload, identities)
