"""Turn the two lab tenants into the SecureCloud Mall: Northstar and Bloom shops.

Retires the old Online Boutique and facilities-vendor stacks, renames the tenants (their
IDs, namespaces and memberships stay), and deploys the shop stacks through the normal
persisted stack operations. Delete the old namespaces in the cluster before running.
"""
from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from .catalog import PLATFORM_TENANT_ID, stack_definition
from .infrastructure.kubernetes import KubernetesInfrastructure
from .store import Store

PLAN = (  # old stack id -> (tenant name, description, new stack id, deployment name)
    ("retail-stack", "Northstar", "Bags and everyday carry. Has the ShipFast plugin installed.", "northstar-shop-stack", "northstar-shop"),
    ("facilities-vendor-stack", "Bloom", "Hand-poured candles.", "bloom-shop-stack", "bloom-shop"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    store = Store(args.database, infrastructure=KubernetesInfrastructure(args.kubeconfig))
    now = time.time()
    run = f"mall-{int(now)}"
    with store.connect() as db:
        admin = db.execute("SELECT id FROM users WHERE administrator=1 AND disabled=0 LIMIT 1").fetchone()
        for old, name, description, new, deployment in PLAN:
            row = db.execute("SELECT id,tenant_id FROM stack_deployments WHERE stack_id IN (?,?) ORDER BY created DESC LIMIT 1", (old, new)).fetchone()
            if row is None:
                raise SystemExit(f"No {old} deployment to convert")
            tenant = row["tenant_id"]
            db.execute("UPDATE tenants SET name=?,description=? WHERE id=?", (name, description, tenant))
            existing = db.execute("SELECT id FROM stack_deployments WHERE tenant_id=? AND stack_id=? AND desired!='deleted'", (tenant, new)).fetchone()
            if existing:  # re-apply so pods pick up new images and settings
                db.execute("INSERT INTO stack_operations VALUES(?,?,?,?,'deploy','queued',?,?,?,NULL)",
                           (str(uuid.uuid4()), admin["id"], tenant, existing["id"], f"{run}:{new}", f"{run}:{new}", now))
                print(f"{name}: re-applying {new}")
                continue
            db.execute("UPDATE workloads SET desired='deleted',observed='deleted',quarantined=0 WHERE tenant_id=?", (tenant,))
            db.execute("UPDATE stack_deployments SET desired='deleted',observed='deleted',name=name||'-retired-'||? WHERE tenant_id=?", (int(now), tenant))
            deployment_id = str(uuid.uuid4())
            db.execute("INSERT INTO stack_deployments(id,tenant_id,name,stack_id,desired,observed,created) VALUES(?,?,?,?,'running','pending',?)",
                       (deployment_id, tenant, deployment, new, now))
            for service in stack_definition(new).services:
                db.execute("INSERT INTO workloads(id,tenant_id,name,template,desired,observed,created,stack_deployment_id) VALUES(?,?,?,?,'running','pending',?,?)",
                           (str(uuid.uuid4()), tenant, service.id, service.template, now, deployment_id))
            db.execute("INSERT INTO stack_operations VALUES(?,?,?,?,'deploy','queued',?,?,?,NULL)",
                       (str(uuid.uuid4()), admin["id"], tenant, deployment_id, f"{run}:{new}", f"{run}:{new}", now))
            print(f"{name}: queued {new}")
        # Platform zone: shared order IDs, payments and email (platform-owned, not a customer tenant).
        db.execute("INSERT OR IGNORE INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
                   (PLATFORM_TENANT_ID, "Mall Platform", "Shared order IDs, payments and email, run by the platform team.", now))
        existing = db.execute("SELECT id FROM stack_deployments WHERE stack_id='platform-stack' AND desired!='deleted'").fetchone()
        deployment_id = existing["id"] if existing else str(uuid.uuid4())
        if not existing:
            db.execute("INSERT INTO stack_deployments(id,tenant_id,name,stack_id,desired,observed,created) VALUES(?,?,?,?,'running','pending',?)",
                       (deployment_id, PLATFORM_TENANT_ID, "mall-platform", "platform-stack", now))
            for service in stack_definition("platform-stack").services:
                db.execute("INSERT INTO workloads(id,tenant_id,name,template,desired,observed,created,stack_deployment_id) VALUES(?,?,?,?,'running','pending',?,?)",
                           (str(uuid.uuid4()), PLATFORM_TENANT_ID, service.id, service.template, now, deployment_id))
        db.execute("INSERT INTO stack_operations VALUES(?,?,?,?,'deploy','queued',?,?,?,NULL)",
                   (str(uuid.uuid4()), admin["id"], PLATFORM_TENANT_ID, deployment_id, f"{run}:platform", f"{run}:platform", now))
        print("Mall Platform: queued platform-stack")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        store.reconcile_stack_operations()
        with store.connect() as db:
            rows = db.execute("SELECT o.status,o.error,s.stack_id FROM stack_operations o JOIN stack_deployments s ON s.id=o.stack_deployment_id WHERE o.idempotency_key LIKE ?", (run + ':%',)).fetchall()
        if rows and all(r["status"] not in {"queued", "running"} for r in rows):
            for r in rows:
                print(f"{r['stack_id']}: {r['status']}" + (f" ({r['error']})" if r["error"] else ""))
            return 0 if all(r["status"] == "succeeded" for r in rows) else 1
        time.sleep(3)
    print("Mall provisioning did not finish before the timeout")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
