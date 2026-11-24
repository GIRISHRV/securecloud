"""Allowlisted live-lab scenarios.

Callers choose a scenario ID only. Sources, targets, ports and payloads are fixed
here and resolved to project-owned lab namespaces on the server; nothing a caller
sends can name a host, port or command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Expect = Literal["allowed", "blocked", "either"]
Kind = Literal["benign", "attack", "verify"]


@dataclass(frozen=True)
class Probe:
    """TCP connection attempts from the scenario source to one catalog service."""
    target_stack: str          # catalog stack id, e.g. "northstar-shop-stack"
    target_service: str        # catalog service id
    port: int
    count: int = 2
    gap: float = 0.05
    expect: Expect = "either"
    direct_pod_ip: bool = False  # bypass the Service and dial the pod IP (needed for port scans)
    label: str = ""
    external_host: str | None = None  # fixed address outside the cluster (reserved TEST-NET only)


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    kind: Kind
    summary: str
    what_to_watch: str
    source_stack: str
    source_service: str
    probes: tuple[Probe, ...] = ()
    checkout: bool = False     # place one real Northstar order instead of TCP probes
    restart_source: bool = False  # replace the source pod (rollout restart) before probing
    tags: tuple[str, ...] = field(default_factory=tuple)


NS, BL, PL = "northstar-shop-stack", "bloom-shop-stack", "platform-stack"

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="normal-checkout",
        title="Place a real order",
        kind="benign",
        summary="The lab customer buys a product on the Northstar storefront. The order goes web → order API → database, and the order API settles it with the shared platform: order ID, payment, email.",
        what_to_watch="Every hop, including the calls into the platform zone, should be FORWARDED and the risk should stay low. The order also appears on the Orders page.",
        source_stack=NS,
        source_service="northstar-web",
        checkout=True,
        tags=("Normal traffic",),
    ),
    Scenario(
        id="plugin-valid-path-burst",
        title="Plugin misuses its valid access",
        kind="attack",
        summary="The hacked ShipFast plugin hammers the Northstar order API it is allowed to use: 60 connections in a few seconds, like bulk-downloading every order.",
        what_to_watch="Policy ALLOWS this (it is an approved path). Watch whether the temporal-graph risk for the plugin rises. This is the known limitation.",
        source_stack=NS,
        source_service="shipfast-plugin",
        probes=(Probe(NS, "northstar-api", 8080, count=60, gap=0.05, expect="allowed", label="Approved order API"),),
        tags=("Valid access misuse", "Temporal model"),
    ),
    Scenario(
        id="plugin-lateral-movement",
        title="Plugin attacks the other shop",
        kind="attack",
        summary="The hacked ShipFast plugin tries Bloom's storefront, order API and database, Northstar's own database, and the shared payment and email services. It was given none of them.",
        what_to_watch="Default-deny should DROP every connection. Bloom is a different tenant, and the plugin may only call Northstar's order API.",
        source_stack=NS,
        source_service="shipfast-plugin",
        probes=(
            Probe(BL, "bloom-api", 8080, expect="blocked", label="Bloom order API"),
            Probe(BL, "bloom-database", 5432, expect="blocked", label="Bloom database"),
            Probe(BL, "bloom-web", 8080, expect="blocked", direct_pod_ip=True, label="Bloom storefront"),
            Probe(NS, "northstar-database", 5432, expect="blocked", label="Northstar database"),
            Probe(PL, "payments", 8080, expect="blocked", label="Shared payments"),
            Probe(PL, "email", 8080, expect="blocked", label="Shared email"),
        ),
        tags=("Lateral movement", "Cross-tenant"),
    ),
    Scenario(
        id="plugin-port-scan",
        title="Plugin port-scans the order API",
        kind="attack",
        summary="The plugin dials common ports on the Northstar order API pod directly, bypassing its Service.",
        what_to_watch="Only 8080 is approved for the plugin; Cilium should DROP 22, 80, 443, 3306, 5432, 6379 and 9000.",
        source_stack=NS,
        source_service="shipfast-plugin",
        probes=tuple(
            Probe(NS, "northstar-api", port, count=1, gap=0.1,
                  expect="allowed" if port == 8080 else "blocked", direct_pod_ip=True, label=f"Port {port}")
            for port in (22, 80, 443, 3306, 5432, 6379, 8080, 9000)
        ),
        tags=("Reconnaissance", "Vertical scan"),
    ),
    Scenario(
        id="containment-check",
        title="Check plugin containment",
        kind="verify",
        summary="Re-tests the plugin's previously approved path to the Northstar order API by pod IP (quarantine also blocks DNS). After quarantine it must be DROPPED; after restore it must be FORWARDED.",
        what_to_watch="Run this after quarantining or restoring the plugin. Northstar keeps taking orders either way.",
        source_stack=NS,
        source_service="shipfast-plugin",
        probes=(Probe(NS, "northstar-api", 8080, count=3, expect="either", direct_pod_ip=True, label="Previously approved path"),),
        tags=("Verification",),
    ),
)

# TEST-NET-3 (RFC 5737): reserved for documentation and never routed, so no real system is contacted.
EXFIL_HOST = "203.0.113.10"

SCENARIOS = SCENARIOS + (
    Scenario(
        id="bloom-attacks-northstar",
        title="Bloom attacks Northstar",
        kind="attack",
        summary="A hacked Bloom order API tries Northstar's order API, database, storefront and its installed plugin.",
        what_to_watch="Tenant walls work in both directions: every connection into Northstar should be DROPPED.",
        source_stack=BL,
        source_service="bloom-api",
        probes=(
            Probe(NS, "northstar-api", 8080, expect="blocked", label="Northstar order API"),
            Probe(NS, "northstar-database", 5432, expect="blocked", label="Northstar database"),
            Probe(NS, "northstar-web", 8080, expect="blocked", direct_pod_ip=True, label="Northstar storefront"),
            Probe(NS, "shipfast-plugin", 8080, expect="blocked", label="ShipFast plugin"),
        ),
        tags=("Lateral movement", "Cross-tenant"),
    ),
    Scenario(
        id="data-exfiltration",
        title="Steal data out of the cluster",
        kind="attack",
        summary="A hacked Northstar order API tries to send data to an outside server (a reserved test address that is never routed).",
        what_to_watch="Default-deny egress should DROP the connection before it leaves the node, so stolen data cannot get out.",
        source_stack=NS,
        source_service="northstar-api",
        probes=(
            Probe(NS, "internet", 443, expect="blocked", external_host=EXFIL_HOST, label="Outside server :443"),
            Probe(NS, "internet", 80, expect="blocked", external_host=EXFIL_HOST, label="Outside server :80"),
        ),
        tags=("Exfiltration", "Egress"),
    ),
    Scenario(
        id="network-sweep",
        title="Plugin sweeps the network",
        kind="attack",
        summary="The hacked plugin tries every service in both shops and the shared platform, one connection each.",
        what_to_watch="Only Northstar's order API is approved for the plugin; everything else should be DROPPED.",
        source_stack=NS,
        source_service="shipfast-plugin",
        probes=tuple(
            Probe(stack, service, port, count=1, gap=0.0, expect="allowed" if service == "northstar-api" else "blocked",
                  direct_pod_ip=service.endswith("-web"), label=label)
            for stack, service, port, label in (
                (NS, "northstar-api", 8080, "Northstar order API"), (NS, "northstar-web", 8080, "Northstar storefront"),
                (NS, "northstar-database", 5432, "Northstar database"), (BL, "bloom-web", 8080, "Bloom storefront"),
                (BL, "bloom-api", 8080, "Bloom order API"), (BL, "bloom-database", 5432, "Bloom database"),
                (PL, "order-ids", 8080, "Order IDs"), (PL, "payments", 8080, "Payments"), (PL, "email", 8080, "Email"),
            )
        ),
        tags=("Reconnaissance", "Horizontal scan"),
    ),
    Scenario(
        id="quarantine-restart",
        title="Restart the quarantined plugin",
        kind="verify",
        summary="Kubernetes replaces the plugin's pod (new pod, new IP), then the lab re-tests its approved path. Quarantine follows the workload label, so a new pod is still cut off.",
        what_to_watch="Run this while the plugin is quarantined: the new pod must still be DROPPED. When not quarantined it stays FORWARDED.",
        source_stack=NS,
        source_service="shipfast-plugin",
        probes=(Probe(NS, "northstar-api", 8080, count=3, expect="either", direct_pod_ip=True, label="New pod → order API"),),
        restart_source=True,
        tags=("Verification", "Pod replacement"),
    ),
)

BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


PROBE_SCRIPT = r"""
import json, socket, sys, threading, time
spec = json.loads(sys.argv[1]); out = []; lock = threading.Lock()
def dial(t):
    for i in range(t["count"]):
        start = time.time()
        try:
            c = socket.create_connection((t["host"], t["port"]), timeout=0.6); c.close(); result = "connected"
        except socket.timeout:
            result = "timeout"
        except ConnectionRefusedError:
            result = "refused"
        except OSError as exc:
            result = "error:" + type(exc).__name__
        with lock:
            out.append({"i": t["i"], "result": result, "ms": round((time.time() - start) * 1000)})
        time.sleep(t["gap"])
threads = [threading.Thread(target=dial, args=(t,)) for t in spec]
for th in threads: th.start()
for th in threads: th.join()
out.sort(key=lambda item: item["i"])
print("LABRESULT " + json.dumps(out))
"""

