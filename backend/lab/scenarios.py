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
    target_stack: str          # "retail-stack" | "facilities-vendor-stack"
    target_service: str        # catalog service id
    port: int
    count: int = 3
    gap: float = 0.2
    expect: Expect = "either"
    direct_pod_ip: bool = False  # bypass the Service and dial the pod IP (needed for port scans)
    label: str = ""


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
    checkout: bool = False     # drive one real storefront checkout instead of TCP probes
    tags: tuple[str, ...] = field(default_factory=tuple)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="normal-checkout",
        title="Place a real order",
        kind="benign",
        summary="A shopper session inside the retail tenant browses, adds a product to the cart and checks out through the live storefront.",
        what_to_watch="Every hop (frontend → checkout → payment, cart, shipping, email) should be FORWARDED by Cilium and the risk score should stay low.",
        source_stack="retail-stack",
        source_service="loadgenerator",
        checkout=True,
        tags=("Normal traffic",),
    ),
    Scenario(
        id="vendor-valid-path-burst",
        title="Vendor misuses its valid access",
        kind="attack",
        summary="Attacker code running as the compromised vendor-api hammers its own approved database path: 60 connections in a few seconds.",
        what_to_watch="Static policy ALLOWS this (it is an approved path). Watch whether the temporal-graph risk for vendor-api rises anyway.",
        source_stack="facilities-vendor-stack",
        source_service="vendor-api",
        probes=(Probe("facilities-vendor-stack", "vendor-database", 5432, count=60, gap=0.05, expect="allowed", label="Approved path, abnormal rate"),),
        tags=("Valid access misuse", "Temporal model"),
    ),
    Scenario(
        id="vendor-lateral-movement",
        title="Vendor pivots into the retail tenant",
        kind="attack",
        summary="The compromised vendor-api tries to reach RetailCo's payment, cart, checkout and cart database services.",
        what_to_watch="Default-deny should DROP every cross-tenant connection, and the drops are independent evidence for an incident.",
        source_stack="facilities-vendor-stack",
        source_service="vendor-api",
        probes=(
            Probe("retail-stack", "paymentservice", 50051, expect="blocked", label="Payment service"),
            Probe("retail-stack", "cartservice", 7070, expect="blocked", label="Cart service"),
            Probe("retail-stack", "checkoutservice", 5050, expect="blocked", label="Checkout service"),
            Probe("retail-stack", "redis-cart", 6379, expect="blocked", label="Cart database"),
        ),
        tags=("Lateral movement", "Cross-tenant"),
    ),
    Scenario(
        id="vendor-port-scan",
        title="Vendor port-scans its database",
        kind="attack",
        summary="vendor-api dials common service ports on the vendor database pod directly, bypassing its Service.",
        what_to_watch="Only 5432 is an approved intent; Cilium should DROP 22, 80, 443, 3306, 6379, 8080 and 9000.",
        source_stack="facilities-vendor-stack",
        source_service="vendor-api",
        probes=tuple(
            Probe("facilities-vendor-stack", "vendor-database", port, count=1, gap=0.1,
                  expect="allowed" if port == 5432 else "blocked", direct_pod_ip=True, label=f"Port {port}")
            for port in (22, 80, 443, 3306, 5432, 6379, 8080, 9000)
        ),
        tags=("Reconnaissance", "Vertical scan"),
    ),
    Scenario(
        id="containment-check",
        title="Check vendor-api containment",
        kind="verify",
        summary="Re-tests vendor-api's previously approved database path by pod IP (quarantine also blocks DNS). After quarantine it must be DROPPED; after restore it must be FORWARDED.",
        what_to_watch="Run this after quarantining or restoring vendor-api. The expected verdict follows its current quarantine state.",
        source_stack="facilities-vendor-stack",
        source_service="vendor-api",
        probes=(Probe("facilities-vendor-stack", "vendor-database", 5432, count=3, expect="either", direct_pod_ip=True, label="Previously approved path"),),
        tags=("Verification",),
    ),
)

BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


PROBE_SCRIPT = r"""
import json, socket, sys, time
spec = json.loads(sys.argv[1]); out = []
for t in spec:
    for i in range(t["count"]):
        start = time.time()
        try:
            c = socket.create_connection((t["host"], t["port"]), timeout=1.0); c.close(); result = "connected"
        except socket.timeout:
            result = "timeout"
        except ConnectionRefusedError:
            result = "refused"
        except OSError as exc:
            result = "error:" + type(exc).__name__
        out.append({"i": t["i"], "result": result, "ms": round((time.time() - start) * 1000)})
        time.sleep(t["gap"])
print("LABRESULT " + json.dumps(out))
"""

CHECKOUT_SCRIPT = r"""
import http.cookiejar, json, re, sys, time, urllib.parse, urllib.request
base = sys.argv[1]
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
steps = []
def call(name, path, data=None):
    start = time.time()
    body = urllib.parse.urlencode(data).encode() if data else None
    try:
        with opener.open(urllib.request.Request(base + path, data=body), timeout=20) as r:
            text = r.read().decode("utf-8", "replace"); status = r.status
    except Exception as exc:
        steps.append({"step": name, "status": None, "error": type(exc).__name__, "ms": round((time.time() - start) * 1000)}); return ""
    steps.append({"step": name, "status": status, "ms": round((time.time() - start) * 1000)}); return text
call("Open storefront", "/")
call("View product", "/product/OLJCESPC7Z")
call("Add to cart", "/cart", {"product_id": "OLJCESPC7Z", "quantity": "1"})
page = call("Checkout", "/cart/checkout", {
    "email": "lab-shopper@example.test", "street_address": "1 Lab Street", "zip_code": "560001",
    "city": "Bengaluru", "state": "KA", "country": "India", "credit_card_number": "4432801561520454",
    "credit_card_expiration_month": "1", "credit_card_expiration_year": str(time.gmtime().tm_year + 2), "credit_card_cvv": "672"})
match = re.search(r"[Cc]onfirmation\s*#?\s*</?[^>]*>?\s*([A-Za-z0-9-]{8,})", page) or re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", page)
print("LABRESULT " + json.dumps({"steps": steps, "order_id": match.group(1) if match else None, "complete": "order is complete" in page.lower() or bool(match)}))
"""
