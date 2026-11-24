"""Allowlisted benchmark scenarios; no arbitrary network targets or commands."""
from __future__ import annotations

from dataclasses import dataclass
import random

from backend.telemetry.schema import NormalizedFlow, WorkloadIdentity


WINDOW_SECONDS = 30
BASE_TIME = 1_700_000_000.0
# Mall topology: two shops, the ShipFast plugin installed in Northstar, and shared payments.
BASE_APPROVED_PORTS = {
    ("northstar-web", "northstar-api"): 8080,
    ("northstar-api", "northstar-database"): 5432,
    ("bloom-web", "bloom-api"): 8080,
    ("bloom-api", "bloom-database"): 5432,
    ("northstar-api", "payments"): 8080,
    ("bloom-api", "payments"): 8080,
    ("shipfast-plugin", "northstar-api"): 8080,  # the plugin's only grant; it syncs occasionally
}
BASE_APPROVED_EDGES = set(BASE_APPROVED_PORTS)
QUIET_EDGES = {("shipfast-plugin", "northstar-api")}


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    malicious: bool
    flows: tuple[NormalizedFlow, ...]
    malicious_event_ids: frozenset[str]
    approved_edges: frozenset[tuple[str, str]]


def _identity(workload_id: str) -> WorkloadIdentity:
    tenant = (
        "bloom" if workload_id.startswith("bloom-")
        else "platform" if workload_id in {"payments", "email", "order-ids"}
        else "northstar"  # northstar-* and the ShipFast plugin installed in Northstar
    )
    return WorkloadIdentity(tenant, workload_id, workload_id)


def _flow(
    event_id: str,
    at: float,
    source: str,
    destination: str,
    port: int,
    approved_edges: set[tuple[str, str]],
    *,
    service_failure: bool = False,
) -> NormalizedFlow:
    source_identity = _identity(source)
    destination_identity = _identity(destination)
    approved = (
        (source, destination) in approved_edges
        and BASE_APPROVED_PORTS.get((source, destination), port) == port
    )
    if service_failure:
        verdict, reason = "dropped", "SERVICE_UNAVAILABLE"
    elif not approved:
        verdict, reason = "dropped", "POLICY_DENIED"
    else:
        verdict, reason = "forwarded", None
    return NormalizedFlow(
        event_id=event_id,
        observed_at=at,
        source=source_identity,
        destination=destination_identity,
        identity_status="resolved",
        verdict=verdict,
        drop_reason=reason,
        protocol="TCP",
        destination_port=port,
        node_name="evaluation-node",
    )


def benign_training_flows(seed: int, windows: int = 20) -> list[NormalizedFlow]:
    rng = random.Random(seed)
    flows: list[NormalizedFlow] = []
    edges = sorted(BASE_APPROVED_EDGES)
    for window in range(windows):
        start = BASE_TIME + window * WINDOW_SECONDS
        for edge_index, (source, destination) in enumerate(edges):
            port = BASE_APPROVED_PORTS[(source, destination)]
            # Busy paths carry 2-4 connections per window; the plugin syncs once every few windows.
            samples = (1 if window % 4 == 0 else 0) if (source, destination) in QUIET_EDGES else 2 + rng.randrange(3)
            for sample in range(samples):
                flows.append(_flow(
                    f"train-{seed}-{window}-{edge_index}-{sample}",
                    start + 1 + sample,
                    source,
                    destination,
                    port,
                    BASE_APPROVED_EDGES,
                ))
    return flows


def build_scenario(scenario_id: str, seed: int, repetition: int) -> Scenario:
    if scenario_id not in scenario_ids():
        raise ValueError(f"Unknown allowlisted scenario: {scenario_id}")
    rng = random.Random(f"{seed}:{repetition}:{scenario_id}")
    start = BASE_TIME + 10_000 + repetition * 600
    approved = set(BASE_APPROVED_EDGES)
    specs: list[tuple[float, str, str, int, bool, bool]] = []

    if scenario_id == "normal_service_traffic":
        for index in range(24):
            source, destination = rng.choice(sorted(approved))
            specs.append((index, source, destination, BASE_APPROVED_PORTS[(source, destination)], False, False))
    elif scenario_id == "legitimate_surge":
        specs.extend((index / 4, "northstar-web", "northstar-api", 8080, False, False) for index in range(80))
    elif scenario_id == "workload_restart":
        specs.extend((index, "bloom-web", "bloom-api", 8080, False, False) for index in range(6))
        specs.extend((45 + index, "bloom-web", "bloom-api", 8080, False, False) for index in range(6))
    elif scenario_id == "new_approved_deployment":
        approved.add(("northstar-reports-web", "northstar-reports-api"))
        specs.extend((index, "northstar-reports-web", "northstar-reports-api", 8080, False, False) for index in range(12))
    elif scenario_id == "temporary_service_failure":
        specs.extend((index, "bloom-api", "bloom-database", 5432, False, True) for index in range(8))
    elif scenario_id == "cross_tenant_attempt":
        specs.extend((index, "northstar-web", "bloom-api", 8080, True, False) for index in range(8))
    elif scenario_id == "horizontal_scan":
        destinations = ["bloom-api", "bloom-database", "northstar-database"]
        specs.extend((index * 2, "northstar-web", destination, 8080, True, False) for index, destination in enumerate(destinations))
    elif scenario_id == "vertical_port_scan":
        for index, port in enumerate([22, 80, 443, 3306, 5432, 6379, 8080, 9000]):
            specs.append((index * 2, "northstar-web", "northstar-api", port, True, False))
    elif scenario_id == "unexpected_destination":
        specs.extend((index, "bloom-api", "northstar-database", 5432, True, False) for index in range(6))
    elif scenario_id == "low_rate_lateral_movement":
        specs.extend((index * 35, "northstar-web", "bloom-api", 8080, True, False) for index in range(4))
    elif scenario_id == "suspicious_approved_path":
        # Abuse of a busy path: indistinguishable from a legitimate surge by volume alone.
        specs.extend((index / 5, "northstar-web", "northstar-api", 8080, True, False) for index in range(100))
    elif scenario_id == "plugin_approved_path_abuse":
        # The hacked plugin floods the order API it is allowed to use (a normally quiet path).
        specs.extend((index / 5, "shipfast-plugin", "northstar-api", 8080, True, False) for index in range(100))
    elif scenario_id == "compromised_plugin_lateral_movement":
        specs.extend((index, "shipfast-plugin", "northstar-api", 8080, False, False) for index in range(2))
        specs.extend((10 + index * 4, "shipfast-plugin", "payments", 8080, True, False) for index in range(6))

    flows: list[NormalizedFlow] = []
    malicious_ids: set[str] = set()
    for index, (offset, source, destination, port, malicious, failure) in enumerate(specs):
        event_id = f"eval-{seed}-{repetition}-{scenario_id}-{index}"
        flows.append(_flow(
            event_id, start + offset, source, destination, port, approved,
            service_failure=failure,
        ))
        if malicious:
            malicious_ids.add(event_id)
    return Scenario(
        scenario_id,
        "suspicious" if malicious_ids else "benign",
        bool(malicious_ids),
        tuple(flows),
        frozenset(malicious_ids),
        frozenset(approved),
    )


def scenario_ids() -> tuple[str, ...]:
    return (
        "normal_service_traffic",
        "legitimate_surge",
        "workload_restart",
        "new_approved_deployment",
        "temporary_service_failure",
        "cross_tenant_attempt",
        "horizontal_scan",
        "vertical_port_scan",
        "unexpected_destination",
        "low_rate_lateral_movement",
        "suspicious_approved_path",
        "plugin_approved_path_abuse",
        "compromised_plugin_lateral_movement",
    )
