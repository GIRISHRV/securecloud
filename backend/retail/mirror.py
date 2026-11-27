"""Forward each shop order to that shop's in-cluster order service.

The storefront writes the order to its own database first; this mirror then sends it
through the Northstar tenant (web -> order API -> database) so a real customer order is
real cluster traffic that Cilium enforces and Hubble records.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request

logger = logging.getLogger(__name__)
UPSTREAM = os.environ.get("SECURECLOUD_NORTHSTAR_UPSTREAM", "http://127.0.0.1:8094")
last_result: dict = {}


def order_payload(order: dict) -> dict:
    items = ", ".join(f"{i['quantity']}x {i['name_snapshot']}" for i in order.get("items", []))
    return {
        "order_number": order["order_number"],
        "customer_email": order["customer"]["email"],
        "items": items[:200] or "-",
        "total": f"{order['total_minor'] / 100:.2f}",
        "status": "Placed",
    }


def mirror_order(order: dict, timeout: float = 5.0, upstream=None) -> dict:
    """``upstream`` is a base URL (port-forward) or a sender(path, payload) -> (status, body)."""
    started = time.time()
    try:
        if callable(upstream):
            status, body = upstream("/api/resources/orders", order_payload(order))
            result = {"ok": status == 201, "status": status, "record": json.loads(body or b"{}") if status == 201 else {}}
        else:
            request = urllib.request.Request(
                f"{upstream or UPSTREAM}/api/resources/orders",
                data=json.dumps(order_payload(order)).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = {"ok": response.status == 201, "status": response.status, "record": json.loads(response.read() or b"{}")}
    except Exception as exc:  # the shop stays usable if the cluster is down
        result = {"ok": False, "error": str(exc) or type(exc).__name__}
    result.update(order_number=order["order_number"], ms=round((time.time() - started) * 1000), at=time.time())
    last_result.clear(); last_result.update(result)
    if not result["ok"]:
        logger.warning("Order %s was not mirrored: %s", order["order_number"], result.get("error") or result.get("status"))
    return result


def mirror_in_background(order: dict, upstream=None) -> None:
    threading.Thread(target=mirror_order, args=(order,), kwargs={"upstream": upstream}, name="order-mirror", daemon=True).start()
