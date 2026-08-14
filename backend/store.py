"""SQLite persistence for the single-node demonstrator; no cluster credentials."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
 password_hash TEXT NOT NULL, administrator INTEGER NOT NULL DEFAULT 0,
 disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_limits (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tenants (
 id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE, description TEXT NOT NULL,
 created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
 tenant_id TEXT NOT NULL REFERENCES tenants(id), user_id TEXT NOT NULL REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('viewer','operator','admin')), PRIMARY KEY(tenant_id,user_id)
);
CREATE TABLE IF NOT EXISTS workloads (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), name TEXT NOT NULL,
 template TEXT NOT NULL CHECK(template IN ('web','api','database')),
 desired TEXT NOT NULL CHECK(desired IN ('running','stopped','deleted')),
 observed TEXT NOT NULL DEFAULT 'pending', quarantined INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL,
 kubernetes_uid TEXT, kubernetes_version TEXT, UNIQUE(tenant_id,name)
);
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 tenant_id TEXT NOT NULL REFERENCES tenants(id), workload_id TEXT NOT NULL REFERENCES workloads(id),
 action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
 idempotency_key TEXT NOT NULL, fingerprint TEXT NOT NULL, created REAL NOT NULL,
 error TEXT, UNIQUE(user_id,idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_operation ON operations(workload_id)
 WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT,
 tenant_id TEXT, action TEXT NOT NULL, resource TEXT, outcome TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traffic_events (
 id TEXT PRIMARY KEY,
 at REAL NOT NULL,
 source_id TEXT NOT NULL,
 destination_id TEXT NOT NULL,
 source_name TEXT NOT NULL,
 destination_name TEXT NOT NULL,
 source_tenant TEXT NOT NULL,
 destination_tenant TEXT NOT NULL,
 port INTEGER NOT NULL,
 decision TEXT NOT NULL CHECK(decision IN ('allowed','denied','inconclusive')),
 reason TEXT NOT NULL CHECK(reason IN ('approved-intent','cross-tenant','default-deny','quarantine','unavailable'))
);
CREATE TABLE IF NOT EXISTS incidents (
 id TEXT PRIMARY KEY,
 source_id TEXT NOT NULL,
 source_name TEXT NOT NULL,
 tenant_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('alert','quarantined','review','restored')),
 reason TEXT NOT NULL,
 created_at REAL NOT NULL,
 restored_at REAL,
 evidence_json TEXT NOT NULL,
 trace_json TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_user(self, username: str, password: str, administrator=False):
        """Local administration only; deliberately not an unauthenticated route."""
        from argon2 import PasswordHasher
        import re
        if not re.fullmatch(r"[a-zA-Z0-9_.@-]{3,100}", username) or not 14 <= len(password) <= 256:
            raise ValueError("Use a valid username and a password of 14–256 characters")
        user_id = str(uuid.uuid4())
        password_hash = PasswordHasher().hash(password)
        with self.connect() as db:
            db.execute("INSERT INTO users(id,username,password_hash,administrator) VALUES(?,?,?,?)",
                       (user_id, username, password_hash, int(administrator)))
            audit(db, user_id, None, "user.created", user_id)
        return user_id

    def reconcile_operations(self):
        """Synchronously reconcile pending/queued operations for local simulation/MVP."""
        with self.connect() as db:
            rows = db.execute("SELECT * FROM operations WHERE status IN ('queued', 'running') ORDER BY created").fetchall()
            for op in rows:
                action = op["action"]
                workload_id = op["workload_id"]
                workload = db.execute("SELECT * FROM workloads WHERE id=?", (workload_id,)).fetchone()
                if not workload:
                    db.execute("UPDATE operations SET status='failed', error='Workload disappeared' WHERE id=?", (op["id"],))
                    continue

                if action == "deploy":
                    k8s_uid = f"k8s-pod-{uuid.uuid4().hex[:12]}"
                    k8s_ver = "v1.28-demo"
                    db.execute("UPDATE workloads SET observed='running', kubernetes_uid=?, kubernetes_version=? WHERE id=?",
                               (k8s_uid, k8s_ver, workload_id))
                    db.execute("UPDATE operations SET status='succeeded' WHERE id=?", (op["id"],))
                elif action == "stop":
                    db.execute("UPDATE workloads SET observed='stopped' WHERE id=?", (workload_id,))
                    db.execute("UPDATE operations SET status='succeeded' WHERE id=?", (op["id"],))
                elif action == "delete":
                    db.execute("UPDATE workloads SET observed='deleted' WHERE id=?", (workload_id,))
                    db.execute("UPDATE operations SET status='succeeded' WHERE id=?", (op["id"],))
                audit(db, op["user_id"], op["tenant_id"], f"workload.{action}.reconciled", workload_id)

    def record_traffic(self, event: dict):
        with self.connect() as db:
            db.execute(
                """INSERT INTO traffic_events
                   (id, at, source_id, destination_id, source_name, destination_name,
                    source_tenant, destination_tenant, port, decision, reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["id"], event["at"], event["sourceId"], event["destinationId"],
                    event["sourceName"], event["destinationName"], event["sourceTenant"],
                    event["destinationTenant"], event["port"], event["decision"], event["reason"]
                )
            )

    def get_traffic(self, limit: int = 500) -> list:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM traffic_events ORDER BY at DESC LIMIT ?", (limit,)).fetchall()
            return [
                {
                    "id": r["id"],
                    "at": r["at"],
                    "sourceId": r["source_id"],
                    "destinationId": r["destination_id"],
                    "sourceName": r["source_name"],
                    "destinationName": r["destination_name"],
                    "sourceTenant": r["source_tenant"],
                    "destinationTenant": r["destination_tenant"],
                    "port": r["port"],
                    "decision": r["decision"],
                    "reason": r["reason"],
                }
                for r in reversed(rows)
            ]

    def create_incident(self, incident: dict):
        with self.connect() as db:
            db.execute(
                """INSERT INTO incidents
                   (id, source_id, source_name, tenant_id, status, reason, created_at, evidence_json, trace_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    incident["id"], incident["sourceId"], incident["sourceName"],
                    incident["tenantId"], incident["status"], incident["reason"],
                    incident["createdAt"], json.dumps(incident["evidence"]), json.dumps(incident["trace"])
                )
            )
            audit(db, "system.detector", incident["tenantId"], "incident.created", incident["id"])

    def get_incidents(self, tenant_id: str = None) -> list:
        with self.connect() as db:
            if tenant_id:
                rows = db.execute("SELECT * FROM incidents WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM incidents ORDER BY created_at DESC").fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r["id"],
                    "sourceId": r["source_id"],
                    "sourceName": r["source_name"],
                    "tenantId": r["tenant_id"],
                    "status": r["status"],
                    "reason": r["reason"],
                    "createdAt": r["created_at"],
                    "restoredAt": r["restored_at"],
                    "evidence": json.loads(r["evidence_json"]),
                    "trace": json.loads(r["trace_json"]),
                })
            return results

    def update_incident_status(self, incident_id: str, new_status: str, trace_entry: dict, actor: str = "operator"):
        with self.connect() as db:
            row = db.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if not row:
                raise ValueError("Incident not found")
            traces = json.loads(row["trace_json"])
            traces.append(trace_entry)
            restored_at = trace_entry["at"] if new_status == "restored" else row["restored_at"]
            db.execute("UPDATE incidents SET status=?, restored_at=?, trace_json=? WHERE id=?",
                       (new_status, restored_at, json.dumps(traces), incident_id))
            
            # If quarantined, update source workload
            if new_status == "quarantined":
                db.execute("UPDATE workloads SET quarantined=1 WHERE id=?", (row["source_id"],))
                audit(db, actor, row["tenant_id"], "workload.quarantined", row["source_id"])
            elif new_status == "restored":
                db.execute("UPDATE workloads SET quarantined=0 WHERE id=?", (row["source_id"],))
                audit(db, actor, row["tenant_id"], "workload.restored", row["source_id"])

    def seed_demo_data(self, admin_id: str):
        """Seed the canonical College and Hospital demonstration environment."""
        now = time.time()
        with self.connect() as db:
            # 1. Tenants
            for tid, tname, tdesc in [
                ("college", "College", "Campus services & learning"),
                ("hospital", "Hospital", "Care services & operations"),
            ]:
                db.execute("INSERT OR REPLACE INTO tenants(id, name, description, created) VALUES(?,?,?,?)",
                           (tid, tname, tdesc, now))
                db.execute("INSERT OR REPLACE INTO memberships(tenant_id, user_id, role) VALUES(?,?,?)",
                           (tid, admin_id, "admin"))

            # 2. Workloads (3 per tenant: web, api, database)
            templates = [
                ("web", 0.25, 128, 80),
                ("api", 0.5, 256, 8080),
                ("database", 0.5, 512, 5432),
            ]
            for tid in ["college", "hospital"]:
                for tmpl, cpu, mem, port in templates:
                    wid = f"{tid}-{tmpl}"
                    wname = f"{tid}-{tmpl}"
                    db.execute(
                        """INSERT OR REPLACE INTO workloads
                           (id, tenant_id, name, template, desired, observed, quarantined, version, created, kubernetes_uid, kubernetes_version)
                           VALUES (?,?,?,?,?,?,?,?,?,'k8s-pod-' || ?,'v1.28-demo')""",
                        (wid, tid, wname, tmpl, "running", "running", 0, 1, now, wid)
                    )
            audit(db, admin_id, None, "demo.seeded", "college,hospital")


def audit(db, actor, tenant, action, resource=None, outcome="accepted"):
    db.execute("INSERT INTO audit(at,actor,tenant_id,action,resource,outcome) VALUES(?,?,?,?,?,?)",
               (time.time(), actor, tenant, action, resource, outcome))
