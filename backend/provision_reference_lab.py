"""Provision the fixed College/Hospital reference stacks through persisted operations."""
from __future__ import annotations

import argparse
from pathlib import Path
import time

from .infrastructure.kubernetes import KubernetesInfrastructure
from .store import Store


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision the SecureCloud reference lab")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    infrastructure = KubernetesInfrastructure(args.kubeconfig)
    store = Store(args.database, infrastructure=infrastructure)
    with store.connect() as db:
        user = db.execute(
            "SELECT id,administrator,disabled FROM users WHERE username=? COLLATE NOCASE",
            (args.username,),
        ).fetchone()
    if not user or not user["administrator"] or user["disabled"]:
        parser.error("username must identify an enabled local administrator")

    store.provision_reference_lab(user["id"])
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        store.reconcile_operations()
        with store.connect() as db:
            rows = db.execute(
                """SELECT w.name,o.status,o.error
                   FROM operations o JOIN workloads w ON w.id=o.workload_id
                   WHERE o.idempotency_key LIKE 'reference-lab:%'
                     AND o.created=(SELECT MAX(o2.created) FROM operations o2 WHERE o2.workload_id=o.workload_id)
                   ORDER BY w.name"""
            ).fetchall()
        if rows and all(row["status"] not in {"queued", "running"} for row in rows):
            for row in rows:
                suffix = f": {row['error']}" if row["error"] else ""
                print(f"{row['name']}: {row['status']}{suffix}")
            return 0 if all(row["status"] == "succeeded" for row in rows) else 1
        time.sleep(2)

    print("Reference lab provisioning did not reach a conclusive state before timeout")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
