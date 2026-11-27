"""First-run provisioning for a fresh server: the mall's testbed shops and shared platform.

Creates the Northstar and Bloom tenants and the platform zone in an empty database and queues
their stacks through the normal persisted stack operations, then waits for the reconciler to
report them running. Idempotent: anything that already exists is left alone, so it is safe to
run on every deploy.

    python -m backend.bootstrap_mall --database /var/lib/securecloud/securecloud.sqlite \\
        --kubeconfig /var/lib/securecloud/securecloud.kubeconfig
"""
from __future__ import annotations

import argparse
import secrets
import time
import uuid
from pathlib import Path

from .catalog import PLATFORM_TENANT_ID, stack_definition
from .infrastructure.kubernetes import KubernetesInfrastructure
from .store import Store, audit

MALL = (  # tenant name, description, stack id, deployment name
    ("Northstar", "Bags and everyday carry. Has the ShipFast plugin installed.", "northstar-shop-stack", "northstar-shop"),
    ("Bloom", "Hand-poured candles.", "bloom-shop-stack", "bloom-shop"),
)


def queue(db, operator: str, tenant: str, stack_id: str, deployment_name: str, run: str, now: float) -> bool:
    if db.execute("SELECT 1 FROM stack_deployments WHERE stack_id=? AND desired!='deleted'", (stack_id,)).fetchone():
        return False
    deployment = str(uuid.uuid4())
    db.execute("INSERT INTO stack_deployments(id,tenant_id,name,stack_id,desired,observed,created) VALUES(?,?,?,?,'running','pending',?)",
               (deployment, tenant, deployment_name, stack_id, now))
    for service in stack_definition(stack_id).services:
        db.execute("INSERT INTO workloads(id,tenant_id,name,template,desired,observed,created,stack_deployment_id) VALUES(?,?,?,?,'running','pending',?,?)",
                   (str(uuid.uuid4()), tenant, service.id, service.template, now, deployment))
    db.execute("INSERT INTO stack_operations VALUES(?,?,?,?,'deploy','queued',?,?,?,NULL)",
               (str(uuid.uuid4()), operator, tenant, deployment, f"{run}:{stack_id}", f"{run}:{stack_id}", now))
    audit(db, "system.bootstrap", tenant, "stack.deploy.requested", deployment)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    store = Store(args.database, infrastructure=KubernetesInfrastructure(args.kubeconfig))
    now, run = time.time(), f"bootstrap-{int(time.time())}"
    with store.connect() as db:
        operator = db.execute("SELECT id FROM users WHERE administrator=1 AND disabled=0 ORDER BY rowid LIMIT 1").fetchone()
    if operator is None:  # internal operator for the reconciler; its password is never used or stored anywhere
        store.create_user("operator", secrets.token_urlsafe(32), administrator=True)
        with store.connect() as db:
            operator = db.execute("SELECT id FROM users WHERE administrator=1 ORDER BY rowid LIMIT 1").fetchone()
    queued = 0
    with store.connect() as db:
        for name, description, stack_id, deployment in MALL:
            row = db.execute("SELECT id FROM tenants WHERE name=?", (name,)).fetchone()
            tenant = row["id"] if row else str(uuid.uuid4())
            if not row:
                db.execute("INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)", (tenant, name, description, now))
                db.execute("INSERT INTO memberships VALUES(?,?,?)", (tenant, operator["id"], "admin"))
            queued += queue(db, operator["id"], tenant, stack_id, deployment, run, now)
        db.execute("INSERT OR IGNORE INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
                   (PLATFORM_TENANT_ID, "Mall Platform", "Shared order IDs, payments and email, run by the platform team.", now))
        db.execute("INSERT OR IGNORE INTO memberships VALUES(?,?,?)", (PLATFORM_TENANT_ID, operator["id"], "admin"))
        queued += queue(db, operator["id"], PLATFORM_TENANT_ID, "platform-stack", "mall-platform", run, now)
    if not queued:
        print("Mall already provisioned.")
        return 0
    print(f"Queued {queued} stack(s); waiting for the reconciler…")
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        store.reconcile_stack_operations()
        with store.connect() as db:
            rows = db.execute("""SELECT o.status,o.error,s.stack_id FROM stack_operations o JOIN stack_deployments s ON s.id=o.stack_deployment_id
                                 WHERE o.idempotency_key LIKE ?""", (run + ":%",)).fetchall()
        if rows and all(r["status"] not in {"queued", "running"} for r in rows):
            for r in rows:
                print(f"{r['stack_id']}: {r['status']}" + (f" ({r['error']})" if r["error"] else ""))
            return 0 if all(r["status"] == "succeeded" for r in rows) else 1
        time.sleep(5)
    print("Provisioning did not finish before the timeout; the API's reconciler will keep trying.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
