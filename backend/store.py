"""SQLite persistence for the single-node demonstrator; no cluster credentials."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .infrastructure import (
    InfrastructureAdapter,
    InfrastructureConflict,
    InfrastructureError,
    InfrastructurePending,
    InfrastructureUnavailable,
    StackObservation,
    StackRequest,
    WorkloadRequest,
)
from .telemetry.schema import NormalizedFlow, WorkloadIdentity

REFERENCE_LAB_REVISION = "0.2.0"

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
CREATE TABLE IF NOT EXISTS stack_deployments (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
 name TEXT NOT NULL, stack_id TEXT NOT NULL,
 desired TEXT NOT NULL CHECK(desired IN ('running','deleted')),
 observed TEXT NOT NULL DEFAULT 'pending', version INTEGER NOT NULL DEFAULT 1,
 created REAL NOT NULL, UNIQUE(tenant_id,name), UNIQUE(tenant_id,stack_id)
);
CREATE TABLE IF NOT EXISTS workloads (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), name TEXT NOT NULL,
 template TEXT NOT NULL CHECK(template IN ('web','api','database')),
 desired TEXT NOT NULL CHECK(desired IN ('running','stopped','deleted')),
 observed TEXT NOT NULL DEFAULT 'pending', quarantined INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL,
 kubernetes_uid TEXT, kubernetes_version TEXT, stack_deployment_id TEXT,
 UNIQUE(tenant_id,name)
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
CREATE TABLE IF NOT EXISTS stack_operations (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
 tenant_id TEXT NOT NULL REFERENCES tenants(id),
 stack_deployment_id TEXT NOT NULL REFERENCES stack_deployments(id),
 action TEXT NOT NULL CHECK(action IN ('deploy')),
 status TEXT NOT NULL DEFAULT 'queued', idempotency_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL, created REAL NOT NULL, error TEXT,
 UNIQUE(user_id,idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_stack_operation
 ON stack_operations(stack_deployment_id) WHERE status IN ('queued','running');
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
 status TEXT NOT NULL CHECK(status IN ('alert','quarantined','review','restored','closed')),
 reason TEXT NOT NULL,
 created_at REAL NOT NULL,
 restored_at REAL,
 evidence_json TEXT NOT NULL,
 trace_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS containment_requests (
 incident_id TEXT PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
 action TEXT NOT NULL CHECK(action IN ('quarantine','restore')),
 status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','inconclusive')),
 requested_by TEXT NOT NULL, requested_at REAL NOT NULL, completed_at REAL,
 error TEXT, policy_uid TEXT, policy_version TEXT
);
CREATE TABLE IF NOT EXISTS normalized_flows (
 event_id TEXT PRIMARY KEY, observed_at REAL NOT NULL,
 source_tenant TEXT, source_workload TEXT, source_name TEXT,
 destination_tenant TEXT, destination_workload TEXT, destination_name TEXT,
 identity_status TEXT NOT NULL CHECK(identity_status IN ('resolved','unmapped')),
 verdict TEXT NOT NULL CHECK(verdict IN ('forwarded','dropped','audit','unknown')),
 drop_reason TEXT, protocol TEXT, destination_port INTEGER, node_name TEXT
);
CREATE INDEX IF NOT EXISTS normalized_flows_time ON normalized_flows(observed_at);
CREATE TABLE IF NOT EXISTS detection_findings (
 id TEXT PRIMARY KEY,
 incident_id TEXT NOT NULL REFERENCES incidents(id),
 model_version TEXT NOT NULL,
 window_start REAL NOT NULL,
 window_end REAL NOT NULL,
 source_id TEXT NOT NULL,
 destination_id TEXT NOT NULL,
 predicted_probability REAL NOT NULL,
 anomaly_score REAL NOT NULL,
 threshold REAL NOT NULL,
 supporting_facts_json TEXT NOT NULL,
 event_ids_json TEXT NOT NULL,
 created_at REAL NOT NULL,
 accumulated_risk REAL NOT NULL DEFAULT 0,
 baseline_score REAL NOT NULL DEFAULT 0,
 response TEXT NOT NULL DEFAULT 'alert'
);
CREATE TABLE IF NOT EXISTS risk_observations (
 model_version TEXT NOT NULL,
 window_start REAL NOT NULL,
 window_end REAL NOT NULL,
 source_id TEXT NOT NULL,
 destination_id TEXT NOT NULL,
 anomaly_score REAL NOT NULL,
 accumulated_risk REAL NOT NULL,
 baseline_score REAL NOT NULL,
 threshold REAL NOT NULL,
 corroborated INTEGER NOT NULL,
 response TEXT NOT NULL CHECK(response IN ('observe','containment-recommended')),
 PRIMARY KEY(model_version,window_start,source_id,destination_id)
);
CREATE TABLE IF NOT EXISTS application_flow_correlations (
 application_event_id TEXT PRIMARY KEY,
 flow_event_id TEXT REFERENCES normalized_flows(event_id) ON DELETE SET NULL,
 status TEXT NOT NULL CHECK(status IN ('exact','inconclusive','unmatched')),
 reason TEXT NOT NULL,
 correlated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS application_flow_correlations_flow
 ON application_flow_correlations(flow_event_id);
"""


class Store:
    def __init__(self, path: Path, infrastructure: InfrastructureAdapter | None = None):
        self.path = path
        self.infrastructure = infrastructure
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(workloads)")
            }
            if "stack_deployment_id" not in columns:
                db.execute("ALTER TABLE workloads ADD COLUMN stack_deployment_id TEXT")
            finding_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(detection_findings)")
            }
            for name, definition in (
                ("accumulated_risk", "REAL NOT NULL DEFAULT 0"),
                ("baseline_score", "REAL NOT NULL DEFAULT 0"),
                ("response", "TEXT NOT NULL DEFAULT 'alert'"),
            ):
                if name not in finding_columns:
                    db.execute(f"ALTER TABLE detection_findings ADD COLUMN {name} {definition}")
            # Several findings may now belong to one open incident per source; rebuild
            # older databases whose incident_id column was UNIQUE.
            unique_incident = any(
                index["unique"] and [column["name"] for column in db.execute(f"PRAGMA index_info('{index['name']}')")] == ["incident_id"]
                for index in db.execute("PRAGMA index_list(detection_findings)")
            )
            if unique_incident:
                columns = ",".join(row["name"] for row in db.execute("PRAGMA table_info(detection_findings)"))
                definition = SCHEMA.split("CREATE TABLE IF NOT EXISTS detection_findings (", 1)[1].split(");", 1)[0]
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute(f"CREATE TABLE detection_findings_new ({definition})")
                db.execute(f"INSERT INTO detection_findings_new ({columns}) SELECT {columns} FROM detection_findings")
                db.execute("DROP TABLE detection_findings")
                db.execute("ALTER TABLE detection_findings_new RENAME TO detection_findings")
                db.execute("PRAGMA foreign_keys=ON")
            db.execute("CREATE INDEX IF NOT EXISTS detection_findings_incident_idx ON detection_findings(incident_id)")
            # Allow the 'closed' (dismissed alert) status on databases created before it existed.
            incident_sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='incidents'").fetchone()[0]
            if "'closed'" not in incident_sql:
                columns = ",".join(row["name"] for row in db.execute("PRAGMA table_info(incidents)"))
                definition = SCHEMA.split("CREATE TABLE IF NOT EXISTS incidents (", 1)[1].split(");", 1)[0]
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute(f"CREATE TABLE incidents_new ({definition})")
                db.execute(f"INSERT INTO incidents_new ({columns}) SELECT {columns} FROM incidents")
                db.execute("DROP TABLE incidents")
                db.execute("ALTER TABLE incidents_new RENAME TO incidents")
                db.execute("PRAGMA foreign_keys=ON")

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
        """Reconcile persisted intent without inferring success from a request."""
        with self.connect() as db:
            rows = db.execute("SELECT * FROM operations WHERE status IN ('queued', 'running') ORDER BY created").fetchall()
            operation_ids = [row["id"] for row in rows]
            for operation_id in operation_ids:
                db.execute("UPDATE operations SET status='running', error=NULL WHERE id=? AND status='queued'", (operation_id,))

        for operation_id in operation_ids:
            with self.connect() as db:
                op = db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
                workload = db.execute("SELECT * FROM workloads WHERE id=?", (op["workload_id"],)).fetchone() if op else None
            if not op or op["status"] not in {"queued", "running"}:
                continue
            if not workload:
                self._finish_operation(op, "failed", "Workload disappeared")
                continue
            if self.infrastructure is None:
                self._finish_operation(op, "inconclusive", "Kubernetes infrastructure is not configured", observed="unknown")
                continue

            try:
                observation = self.infrastructure.reconcile(op["action"], WorkloadRequest.from_mapping(workload))
            except InfrastructurePending as exc:
                if exc.observation is not None:
                    with self.connect() as db:
                        db.execute(
                            "UPDATE workloads SET observed=?, kubernetes_uid=?, kubernetes_version=? WHERE id=?",
                            (
                                exc.observation.state,
                                exc.observation.uid,
                                exc.observation.resource_version,
                                op["workload_id"],
                            ),
                        )
                continue
            except InfrastructureUnavailable as exc:
                self._finish_operation(op, "inconclusive", str(exc), observed="unknown")
            except (InfrastructureConflict, InfrastructureError) as exc:
                self._finish_operation(op, "failed", str(exc))
            else:
                self._finish_operation(
                    op,
                    "succeeded",
                    None,
                    observed=observation.state,
                    uid=observation.uid,
                    resource_version=observation.resource_version,
                )

    def reconcile_stack_operations(self):
        """Reconcile one fixed composite stack as a serialized persisted operation."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT id FROM stack_operations "
                "WHERE status IN ('queued','running') ORDER BY created"
            ).fetchall()
            operation_ids = [row["id"] for row in rows]
            for operation_id in operation_ids:
                db.execute(
                    "UPDATE stack_operations SET status='running',error=NULL "
                    "WHERE id=? AND status='queued'",
                    (operation_id,),
                )

        for operation_id in operation_ids:
            with self.connect() as db:
                operation = db.execute(
                    "SELECT * FROM stack_operations WHERE id=?", (operation_id,)
                ).fetchone()
                stack = (
                    db.execute(
                        "SELECT * FROM stack_deployments WHERE id=?",
                        (operation["stack_deployment_id"],),
                    ).fetchone()
                    if operation
                    else None
                )
                component_rows = (
                    db.execute(
                        "SELECT * FROM workloads WHERE stack_deployment_id=? "
                        "ORDER BY name",
                        (stack["id"],),
                    ).fetchall()
                    if stack
                    else []
                )
            if not operation or operation["status"] not in {"queued", "running"}:
                continue
            if not stack or not component_rows:
                self._finish_stack_operation(
                    operation, "failed", "Stack deployment disappeared"
                )
                continue
            if self.infrastructure is None:
                self._finish_stack_operation(
                    operation,
                    "inconclusive",
                    "Kubernetes infrastructure is not configured",
                    observed="unknown",
                )
                continue

            request = StackRequest.from_mapping(stack)
            components = {
                row["name"]: WorkloadRequest.from_mapping(row)
                for row in component_rows
            }
            try:
                observation = self.infrastructure.reconcile_stack(
                    operation["action"], request, components
                )
            except InfrastructurePending as exc:
                if isinstance(exc.observation, StackObservation):
                    self._record_stack_observation(stack["id"], exc.observation)
                continue
            except InfrastructureUnavailable as exc:
                self._finish_stack_operation(
                    operation, "inconclusive", str(exc), observed="unknown"
                )
            except (InfrastructureConflict, InfrastructureError) as exc:
                self._finish_stack_operation(operation, "failed", str(exc))
            else:
                self._record_stack_observation(stack["id"], observation)
                self._finish_stack_operation(
                    operation, "succeeded", None, observed=observation.state
                )

    def _record_stack_observation(
        self, deployment_id: str, observation: StackObservation
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE stack_deployments SET observed=? WHERE id=?",
                (observation.state, deployment_id),
            )
            for name, component in observation.components.items():
                db.execute(
                    """UPDATE workloads
                       SET observed=?,kubernetes_uid=?,kubernetes_version=?
                       WHERE stack_deployment_id=? AND name=?""",
                    (
                        component.state,
                        component.uid,
                        component.resource_version,
                        deployment_id,
                        name,
                    ),
                )

    def _finish_stack_operation(
        self,
        operation,
        status: str,
        error: str | None,
        *,
        observed: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE stack_operations SET status=?,error=? WHERE id=?",
                (status, error, operation["id"]),
            )
            if observed is not None:
                db.execute(
                    "UPDATE stack_deployments SET observed=? WHERE id=?",
                    (observed, operation["stack_deployment_id"]),
                )
                if status != "succeeded":
                    db.execute(
                        "UPDATE workloads SET observed=? WHERE stack_deployment_id=?",
                        (observed, operation["stack_deployment_id"]),
                    )
            audit(
                db,
                operation["user_id"],
                operation["tenant_id"],
                f"stack.{operation['action']}.reconciled",
                operation["stack_deployment_id"],
                outcome=status,
            )

    def request_containment(self, incident_id: str, action: str, actor: str) -> dict:
        if action not in {"quarantine", "restore"}:
            raise ValueError("Unsupported containment action")
        with self.connect() as db:
            incident = db.execute(
                "SELECT * FROM incidents WHERE id=?", (incident_id,)
            ).fetchone()
            if not incident:
                raise ValueError("Incident not found")
            workload = db.execute(
                "SELECT id FROM workloads WHERE id=? AND tenant_id=?",
                (incident["source_id"], incident["tenant_id"]),
            ).fetchone()
            if not workload:
                raise ValueError("Incident source workload not found")
            if action == "quarantine" and incident["status"] not in {"alert", "quarantined"}:
                raise ValueError("Only an active alert can be quarantined")
            if action == "restore" and incident["status"] != "review":
                raise ValueError("Complete incident review before restore")
            now = time.time()
            db.execute(
                """INSERT INTO containment_requests
                   (incident_id,action,status,requested_by,requested_at,completed_at,error,policy_uid,policy_version)
                   VALUES(?,?,'queued',?,?,NULL,NULL,NULL,NULL)
                   ON CONFLICT(incident_id) DO UPDATE SET
                    action=excluded.action,status='queued',requested_by=excluded.requested_by,
                    requested_at=excluded.requested_at,completed_at=NULL,error=NULL,
                    policy_uid=NULL,policy_version=NULL""",
                (incident_id, action, actor, now),
            )
            audit(
                db,
                actor,
                incident["tenant_id"],
                f"containment.{action}.requested",
                incident["source_id"],
                outcome="queued",
            )
        return self.get_containment_request(incident_id)

    def get_containment_request(self, incident_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM containment_requests WHERE incident_id=?", (incident_id,)
            ).fetchone()
        return dict(row) if row else None

    def reconcile_containment_requests(self):
        with self.connect() as db:
            rows = db.execute(
                """SELECT c.*, i.source_id, i.source_name, i.tenant_id,
                          w.name AS workload_name,w.template,w.kubernetes_uid,w.kubernetes_version
                   FROM containment_requests c
                   JOIN incidents i ON i.id=c.incident_id
                   JOIN workloads w ON w.id=i.source_id
                   WHERE c.status IN ('queued','running','inconclusive')
                   ORDER BY c.requested_at"""
            ).fetchall()
            ids = [row["incident_id"] for row in rows]
            for incident_id in ids:
                db.execute(
                    "UPDATE containment_requests SET status='running',error=NULL WHERE incident_id=?",
                    (incident_id,),
                )

        for item in rows:
            if self.infrastructure is None:
                self._finish_containment(item, "inconclusive", "Kubernetes infrastructure is not configured")
                continue
            request = WorkloadRequest(
                item["source_id"], item["tenant_id"], item["workload_name"],
                item["template"], item["kubernetes_uid"], item["kubernetes_version"],
            )
            try:
                observation = self.infrastructure.reconcile_quarantine(
                    request, item["action"] == "quarantine"
                )
            except (InfrastructurePending, InfrastructureUnavailable) as exc:
                self._finish_containment(item, "inconclusive", str(exc))
            except (InfrastructureConflict, InfrastructureError) as exc:
                self._finish_containment(item, "failed", str(exc))
            else:
                self._finish_containment(
                    item,
                    "succeeded",
                    None,
                    observation.policy_uid,
                    observation.resource_version,
                )

    def _finish_containment(
        self, item, status: str, error: str | None,
        policy_uid: str | None = None, policy_version: str | None = None,
    ):
        with self.connect() as db:
            current = db.execute(
                "SELECT * FROM containment_requests WHERE incident_id=?",
                (item["incident_id"],),
            ).fetchone()
            if not current or current["action"] != item["action"]:
                return
            completed = time.time() if status == "succeeded" else None
            db.execute(
                """UPDATE containment_requests
                   SET status=?,completed_at=?,error=?,policy_uid=?,policy_version=?
                   WHERE incident_id=?""",
                (status, completed, error, policy_uid, policy_version, item["incident_id"]),
            )
            if status == "succeeded":
                incident = db.execute(
                    "SELECT * FROM incidents WHERE id=?", (item["incident_id"],)
                ).fetchone()
                traces = json.loads(incident["trace_json"])
                new_status = "quarantined" if item["action"] == "quarantine" else "restored"
                detail = (
                    "Cilium ingress and egress deny policy was observed for this workload."
                    if item["action"] == "quarantine"
                    else "The Cilium quarantine policy was removed and the approved tenant policies were reconciled."
                )
                traces.append({
                    "at": completed,
                    "title": f"Response: {new_status}",
                    "detail": detail,
                })
                db.execute(
                    "UPDATE incidents SET status=?,restored_at=?,trace_json=? WHERE id=?",
                    (
                        new_status,
                        completed if new_status == "restored" else incident["restored_at"],
                        json.dumps(traces),
                        item["incident_id"],
                    ),
                )
                db.execute(
                    "UPDATE workloads SET quarantined=? WHERE id=?",
                    (int(item["action"] == "quarantine"), item["source_id"]),
                )
            audit(
                db,
                item["requested_by"],
                item["tenant_id"],
                f"containment.{item['action']}.reconciled",
                item["source_id"],
                outcome=status,
            )

    def _finish_operation(self, op, status: str, error: str | None, observed: str | None = None,
                          uid: str | None = None, resource_version: str | None = None):
        with self.connect() as db:
            db.execute("UPDATE operations SET status=?, error=? WHERE id=?", (status, error, op["id"]))
            if observed is not None:
                if status == "succeeded":
                    db.execute(
                        "UPDATE workloads SET observed=?, kubernetes_uid=?, kubernetes_version=? WHERE id=?",
                        (observed, uid, resource_version, op["workload_id"]),
                    )
                else:
                    db.execute("UPDATE workloads SET observed=? WHERE id=?", (observed, op["workload_id"]))
            audit(
                db,
                op["user_id"],
                op["tenant_id"],
                f"workload.{op['action']}.reconciled",
                op["workload_id"],
                outcome=status,
            )

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

    def workload_identities(self) -> list[WorkloadIdentity]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT tenant_id,id,name FROM workloads ORDER BY tenant_id,id",
            ).fetchall()
        return [
            WorkloadIdentity(row["tenant_id"], row["id"], row["name"])
            for row in rows
        ]

    def detection_workloads(self) -> list[dict]:
        """Return bounded model features; no infrastructure credentials are exposed."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT id,tenant_id,template,desired,observed,quarantined
                   FROM workloads WHERE desired!='deleted' ORDER BY tenant_id,id""",
            ).fetchall()
        return [
            {
                "id": row["id"],
                "tenant_id": row["tenant_id"],
                "template": row["template"],
                "running": row["desired"] == "running" and row["observed"] == "running",
                "quarantined": bool(row["quarantined"]),
            }
            for row in rows
        ]

    def ingest_normalized_flows(self, flows: list[NormalizedFlow]) -> int:
        inserted = 0
        with self.connect() as db:
            for flow in flows:
                result = db.execute(
                    """INSERT OR IGNORE INTO normalized_flows
                       (event_id,observed_at,source_tenant,source_workload,source_name,
                        destination_tenant,destination_workload,destination_name,
                        identity_status,verdict,drop_reason,protocol,destination_port,node_name)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        flow.event_id,
                        flow.observed_at,
                        flow.source.tenant_id if flow.source else None,
                        flow.source.workload_id if flow.source else None,
                        flow.source.workload_name if flow.source else None,
                        flow.destination.tenant_id if flow.destination else None,
                        flow.destination.workload_id if flow.destination else None,
                        flow.destination.workload_name if flow.destination else None,
                        flow.identity_status,
                        flow.verdict,
                        flow.drop_reason,
                        flow.protocol,
                        flow.destination_port,
                        flow.node_name,
                    ),
                )
                inserted += result.rowcount
        return inserted

    def get_normalized_flows(
        self,
        *,
        start: float | None = None,
        end: float | None = None,
        limit: int = 100_000,
    ) -> list[NormalizedFlow]:
        if limit <= 0 or limit > 1_000_000:
            raise ValueError("Invalid telemetry query limit")
        clauses: list[str] = []
        parameters: list[float | int] = []
        if start is not None:
            clauses.append("observed_at>=?")
            parameters.append(start)
        if end is not None:
            clauses.append("observed_at<?")
            parameters.append(end)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT * FROM (
                       SELECT * FROM normalized_flows {where}
                       ORDER BY observed_at DESC,event_id DESC LIMIT ?
                     ) ORDER BY observed_at,event_id""",
                parameters,
            ).fetchall()
        return [
            NormalizedFlow(
                event_id=row["event_id"],
                observed_at=row["observed_at"],
                source=(
                    WorkloadIdentity(
                        row["source_tenant"],
                        row["source_workload"],
                        row["source_name"],
                    )
                    if row["source_workload"]
                    else None
                ),
                destination=(
                    WorkloadIdentity(
                        row["destination_tenant"],
                        row["destination_workload"],
                        row["destination_name"],
                    )
                    if row["destination_workload"]
                    else None
                ),
                identity_status=row["identity_status"],
                verdict=row["verdict"],
                drop_reason=row["drop_reason"],
                protocol=row["protocol"],
                destination_port=row["destination_port"],
                node_name=row["node_name"],
            )
            for row in rows
        ]

    def correlate_application_events(
        self, application_events: list[dict], *, tolerance_seconds: float = 5.0
    ) -> int:
        """Link bounded application events to flows without treating time as proof.

        A link is exact only when one resolved flow matches tenant, workload
        identities, protocol, destination port, and the bounded time window.
        Zero or multiple candidates remain explicit non-proof states.
        """
        if not 0.1 <= tolerance_seconds <= 30:
            raise ValueError("Invalid correlation tolerance")
        if len(application_events) > 1_000:
            raise ValueError("Too many application events to correlate")
        updated = 0
        with self.connect() as db:
            for event in application_events:
                occurred_at = float(event["occurred_at"])
                rows = db.execute(
                    """SELECT * FROM normalized_flows
                       WHERE identity_status='resolved'
                         AND observed_at BETWEEN ? AND ?
                         AND source_tenant=?
                       ORDER BY observed_at,event_id""",
                    (
                        occurred_at - tolerance_seconds,
                        occurred_at + tolerance_seconds,
                        event["tenant_id"],
                    ),
                ).fetchall()
                candidates = []
                for row in rows:
                    source_matches = event["source_workload"] in {
                        row["source_workload"], row["source_name"]
                    }
                    destination_matches = event["destination_workload"] in {
                        row["destination_workload"], row["destination_name"]
                    }
                    port_matches = (
                        event.get("destination_port") is None
                        or event["destination_port"] == row["destination_port"]
                    )
                    protocol_matches = (
                        not event.get("protocol")
                        or not row["protocol"]
                        or event["protocol"].upper() == row["protocol"].upper()
                    )
                    if source_matches and destination_matches and port_matches and protocol_matches:
                        candidates.append(row)
                if len(candidates) == 1:
                    flow_id, status, reason = (
                        candidates[0]["event_id"],
                        "exact",
                        "one resolved flow matched identity, protocol, port, and time window",
                    )
                elif candidates:
                    flow_id, status, reason = (
                        None,
                        "inconclusive",
                        f"{len(candidates)} flows matched; timing alone cannot identify one request",
                    )
                else:
                    flow_id, status, reason = (
                        None,
                        "unmatched",
                        "no resolved flow matched the bounded correlation window",
                    )
                result = db.execute(
                    """INSERT INTO application_flow_correlations
                       (application_event_id,flow_event_id,status,reason,correlated_at)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(application_event_id) DO UPDATE SET
                         flow_event_id=excluded.flow_event_id,status=excluded.status,
                         reason=excluded.reason,correlated_at=excluded.correlated_at""",
                    (event["id"], flow_id, status, reason, time.time()),
                )
                updated += result.rowcount
        return updated

    def application_flow_correlations(self, application_event_ids: list[str]) -> dict[str, dict]:
        if len(application_event_ids) > 1_000:
            raise ValueError("Too many correlation records requested")
        if not application_event_ids:
            return {}
        placeholders = ",".join("?" for _ in application_event_ids)
        with self.connect() as db:
            rows = db.execute(
                f"""SELECT c.*,f.observed_at,f.source_workload,f.source_name,
                            f.destination_workload,f.destination_name,f.verdict,
                            f.drop_reason,f.protocol,f.destination_port
                     FROM application_flow_correlations c
                     LEFT JOIN normalized_flows f ON f.event_id=c.flow_event_id
                     WHERE c.application_event_id IN ({placeholders})""",
                application_event_ids,
            ).fetchall()
        return {row["application_event_id"]: dict(row) for row in rows}

    def retail_security_scope(self, retail_tenant_id: str) -> set[str]:
        """Return the explicitly deployed retail/vendor lab tenant scope."""
        with self.connect() as db:
            rows = db.execute(
                """SELECT DISTINCT tenant_id FROM stack_deployments
                   WHERE desired!='deleted'
                     AND stack_id IN ('retail-stack','facilities-vendor-stack')"""
            ).fetchall()
        # The retail-domain tenant reference is also valid when both planes use
        # the same stable tenant ID (for tests and future configured adapters).
        return {retail_tenant_id, *(row["tenant_id"] for row in rows)}

    def get_normalized_traffic(self, limit: int = 100) -> list[dict]:
        """Project resolved Hubble flows into the portal's traffic evidence model."""
        if limit <= 0 or limit > 1_000:
            raise ValueError("Invalid telemetry query limit")
        with self.connect() as db:
            rows = db.execute(
                """WITH ranked AS (
                     SELECT normalized_flows.*,
                            source.template AS source_template,
                            destination.template AS destination_template,
                            ROW_NUMBER() OVER (
                              PARTITION BY source_workload,destination_workload,
                                           destination_port,verdict
                              ORDER BY observed_at DESC,event_id DESC
                            ) AS connection_rank
                     FROM normalized_flows
                     JOIN workloads source ON source.id=normalized_flows.source_workload
                     JOIN workloads destination ON destination.id=normalized_flows.destination_workload
                     WHERE identity_status='resolved'
                       AND verdict IN ('forwarded','dropped')
                       AND (
                         verdict='dropped'
                         OR (
                           verdict='forwarded'
                           AND source.tenant_id=destination.tenant_id
                           AND (
                             (source.template='web' AND destination.template='api'
                               AND destination_port=8080)
                             OR (source.template='api' AND destination.template='database'
                               AND destination_port=5432)
                           )
                         )
                       )
                   )
                   SELECT * FROM ranked WHERE connection_rank=1
                   ORDER BY observed_at DESC,event_id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        events = []
        seen_connections: set[tuple] = set()
        for row in reversed(rows):
            cross_tenant = row["source_tenant"] != row["destination_tenant"]
            decision = "allowed" if row["verdict"] == "forwarded" else "denied"
            approved_direction = (
                row["source_tenant"] == row["destination_tenant"]
                and (
                    (row["source_template"] == "web" and row["destination_template"] == "api" and row["destination_port"] == 8080)
                    or (row["source_template"] == "api" and row["destination_template"] == "database" and row["destination_port"] == 5432)
                )
            )
            if decision == "allowed" and not approved_direction:
                continue
            connection_key = (
                row["source_workload"],
                row["destination_workload"],
                row["destination_port"],
                row["verdict"],
                int(row["observed_at"] // 5),
            )
            if connection_key in seen_connections:
                continue
            seen_connections.add(connection_key)
            reason = (
                "cross-tenant"
                if cross_tenant
                else "approved-intent"
                if decision == "allowed"
                else "default-deny"
            )
            events.append({
                "id": row["event_id"],
                "at": row["observed_at"],
                "sourceId": row["source_workload"],
                "destinationId": row["destination_workload"],
                "sourceName": row["source_name"],
                "destinationName": row["destination_name"],
                "sourceTenant": row["source_tenant"],
                "destinationTenant": row["destination_tenant"],
                "port": row["destination_port"] or 1,
                "decision": decision,
                "reason": reason,
            })
        return events

    def approved_edges(self) -> set[tuple[str, str]]:
        """Return approved intents: generic web→API and API→database template edges plus
        every composite stack's declared service dependencies from the server catalog."""
        from .catalog import stack_definition

        with self.connect() as db:
            rows = db.execute(
                """SELECT source.id,destination.id
                   FROM workloads source
                   JOIN workloads destination ON destination.tenant_id=source.tenant_id
                   WHERE source.observed='running' AND destination.observed='running'
                     AND ((source.template='web' AND destination.template='api')
                       OR (source.template='api' AND destination.template='database'))""",
            ).fetchall()
            edges = {(row[0], row[1]) for row in rows}
            for stack in db.execute("SELECT id,stack_id FROM stack_deployments WHERE desired!='deleted'").fetchall():
                definition = stack_definition(stack["stack_id"])
                if definition is None:
                    continue
                members = {
                    row["name"]: row["id"]
                    for row in db.execute(
                        "SELECT id,name FROM workloads WHERE stack_deployment_id=? AND observed='running'",
                        (stack["id"],),
                    )
                }
                for service in definition.services:
                    for dependency in service.dependencies:
                        if service.id in members and dependency in members:
                            edges.add((members[service.id], members[dependency]))
        return edges

    def record_detection_finding(self, finding, evidence: list[dict]) -> bool:
        """Persist one idempotent model finding and its linked incident."""
        incident_id = f"incident-{finding.id}"
        with self.connect() as db:
            if db.execute("SELECT 1 FROM detection_findings WHERE id=?", (finding.id,)).fetchone():
                return False
            flow_ids = [item["id"] for item in evidence]
            references_by_flow: dict[str, list[str]] = {}
            if flow_ids:
                placeholders = ",".join("?" for _ in flow_ids)
                links = db.execute(
                    f"""SELECT flow_event_id,application_event_id
                         FROM application_flow_correlations
                         WHERE status='exact' AND flow_event_id IN ({placeholders})""",
                    flow_ids,
                ).fetchall()
                for link in links:
                    references_by_flow.setdefault(link["flow_event_id"], []).append(
                        link["application_event_id"]
                    )
            incident_evidence = [
                dict(
                    item,
                    applicationEventRefs=sorted(references_by_flow.get(item["id"], [])),
                )
                for item in evidence
            ]
            reason = (
                f"Unexpected graph edge scored {finding.anomaly_score:.3f} "
                f"(threshold {finding.threshold:.3f})"
            )
            trace = [{
                "at": finding.created_at,
                "title": "Graph anomaly detected",
                "detail": (
                    f"{finding.model_version} assigned probability "
                    f"{finding.predicted_probability:.3f}; supporting facts: "
                    f"{', '.join(key for key, value in finding.supporting_facts.items() if value)}"
                ),
            }]
            # One open case per source workload: further findings for a workload that
            # already has an unresolved incident are attached to it as evidence, so a
            # multi-target attack (or attempts while quarantined) stays one incident.
            open_incident = db.execute(
                """SELECT id,evidence_json,trace_json FROM incidents
                   WHERE source_id=? AND status IN ('alert','quarantined','review')
                   ORDER BY created_at DESC LIMIT 1""",
                (finding.source_id,),
            ).fetchone()
            if open_incident:
                incident_id = open_incident["id"]
                existing = json.loads(open_incident["evidence_json"])
                known = {item["id"] for item in existing}
                merged = existing + [item for item in incident_evidence if item["id"] not in known]
                merged_trace = json.loads(open_incident["trace_json"]) + [{
                    "at": finding.created_at,
                    "title": "Additional anomalous edge",
                    "detail": (
                        f"{finding.source_name} → {next((item.get('destinationName') for item in evidence if item.get('destinationName')), finding.destination_id)} scored "
                        f"{finding.anomaly_score:.3f} (threshold {finding.threshold:.3f}); "
                        f"{len(merged) - len(existing)} new flow record(s) attached"
                    ),
                }]
                db.execute(
                    "UPDATE incidents SET evidence_json=?,trace_json=? WHERE id=?",
                    (json.dumps(merged[-1000:]), json.dumps(merged_trace[-200:]), incident_id),
                )
            else:
                db.execute(
                    """INSERT INTO incidents
                       (id,source_id,source_name,tenant_id,status,reason,created_at,evidence_json,trace_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        incident_id,
                        finding.source_id,
                        finding.source_name,
                        finding.source_tenant,
                        "alert",
                        reason,
                        finding.created_at,
                        json.dumps(incident_evidence),
                        json.dumps(trace),
                    ),
                )
            db.execute(
                """INSERT INTO detection_findings
                   (id,incident_id,model_version,window_start,window_end,source_id,destination_id,
                    predicted_probability,anomaly_score,threshold,supporting_facts_json,event_ids_json,
                    created_at,accumulated_risk,baseline_score,response)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    finding.id,
                    incident_id,
                    finding.model_version,
                    finding.window_start,
                    finding.window_end,
                    finding.source_id,
                    finding.destination_id,
                    finding.predicted_probability,
                    finding.anomaly_score,
                    finding.threshold,
                    json.dumps(finding.supporting_facts, sort_keys=True),
                    json.dumps(finding.event_ids),
                    finding.created_at,
                    finding.accumulated_risk,
                    finding.baseline_score,
                    finding.response,
                ),
            )
            audit(
                db, f"system.detector:{finding.model_version}", finding.source_tenant,
                "incident.updated" if open_incident else "incident.created", incident_id,
            )
        return not open_incident

    def record_risk_observations(self, observations) -> int:
        """Persist replay-safe model scores for portal history and evaluation."""
        inserted = 0
        with self.connect() as db:
            for observation in observations:
                result = db.execute(
                    """INSERT OR IGNORE INTO risk_observations
                       (model_version,window_start,window_end,source_id,destination_id,
                        anomaly_score,accumulated_risk,baseline_score,threshold,corroborated,response)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        observation.model_version,
                        observation.window_start,
                        observation.window_end,
                        observation.source_id,
                        observation.destination_id,
                        observation.anomaly_score,
                        observation.accumulated_risk,
                        observation.baseline_score,
                        observation.threshold,
                        int(observation.corroborated),
                        observation.response,
                    ),
                )
                inserted += result.rowcount
        return inserted

    def risk_observations(self, limit: int = 120) -> list[dict]:
        if limit <= 0 or limit > 1_000:
            raise ValueError("Invalid risk observation limit")
        highlight_limit = min(12, max(0, limit - 1))
        with self.connect() as db:
            rows = db.execute(
                """WITH recent AS (
                       SELECT * FROM risk_observations
                       ORDER BY window_end DESC,source_id,destination_id LIMIT ?
                   ), highlighted AS (
                       SELECT * FROM risk_observations
                       ORDER BY (response='containment-recommended') DESC,
                                anomaly_score DESC,window_end DESC LIMIT ?
                   ), selected AS (
                       SELECT * FROM recent
                       UNION
                       SELECT * FROM highlighted
                   )
                   SELECT selected.*, source.tenant_id,
                          source.name AS source_name,
                          destination.name AS destination_name
                   FROM selected
                   LEFT JOIN workloads source ON source.id=selected.source_id
                   LEFT JOIN workloads destination ON destination.id=selected.destination_id
                   ORDER BY window_end DESC,source_id,destination_id""",
                (limit, highlight_limit),
            ).fetchall()
        ranked = sorted(
            rows,
            key=lambda row: (
                row["response"] == "containment-recommended",
                row["accumulated_risk"],
                row["anomaly_score"],
                row["window_end"],
            ),
            reverse=True,
        )
        recent = sorted(rows, key=lambda row: row["window_end"], reverse=True)
        selected = {}
        for row in ranked[:highlight_limit]:
            key = (row["model_version"], row["window_start"], row["source_id"], row["destination_id"])
            selected[key] = row
        for row in recent:
            if len(selected) >= limit:
                break
            key = (row["model_version"], row["window_start"], row["source_id"], row["destination_id"])
            selected[key] = row
        rows = sorted(selected.values(), key=lambda row: row["window_end"])
        return [
            {
                "modelVersion": row["model_version"],
                "windowStart": row["window_start"],
                "windowEnd": row["window_end"],
                "sourceId": row["source_id"],
                "destinationId": row["destination_id"],
                "sourceName": row["source_name"] or row["source_id"],
                "destinationName": row["destination_name"] or row["destination_id"],
                "anomalyScore": row["anomaly_score"],
                "accumulatedRisk": row["accumulated_risk"],
                "baselineScore": row["baseline_score"],
                "threshold": row["threshold"],
                "corroborated": bool(row["corroborated"]),
                "response": row["response"],
                "tenantId": row["tenant_id"],
            }
            for row in rows
        ]

    def detection_findings(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM detection_findings ORDER BY created_at,id").fetchall()
        return [
            {
                **dict(row),
                "supporting_facts": json.loads(row["supporting_facts_json"]),
                "event_ids": json.loads(row["event_ids_json"]),
            }
            for row in rows
        ]

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
            if new_status == "review" and row["status"] not in {"quarantined", "review"}:
                raise ValueError("Only a quarantined incident can enter review")
            if new_status == "closed" and row["status"] != "alert":
                raise ValueError("Only an uncontained alert can be dismissed")
            traces = json.loads(row["trace_json"])
            traces.append(trace_entry)
            restored_at = trace_entry["at"] if new_status == "restored" else row["restored_at"]
            db.execute("UPDATE incidents SET status=?, restored_at=?, trace_json=? WHERE id=?",
                       (new_status, restored_at, json.dumps(traces), incident_id))
            if new_status == "closed":
                audit(db, actor, row["tenant_id"], "incident.dismissed", incident_id)
            

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

    def provision_reference_lab(self, admin_id: str):
        """Queue the fixed College/Hospital stack through the real reconciler."""
        now = time.time()
        with self.connect() as db:
            for tenant_id, name, description in [
                ("college", "School", "Academic management services"),
                ("hospital", "Hospital", "Healthcare management services"),
            ]:
                db.execute(
                    """INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description""",
                    (tenant_id, name, description, now),
                )
                db.execute(
                    "INSERT OR REPLACE INTO memberships(tenant_id,user_id,role) VALUES(?,?,?)",
                    (tenant_id, admin_id, "admin"),
                )
                for template in ("database", "api", "web"):
                    workload_id = f"{tenant_id}-{template}"
                    db.execute(
                        """INSERT OR IGNORE INTO workloads
                           (id,tenant_id,name,template,desired,observed,created)
                           VALUES(?,?,?,?,?,'pending',?)""",
                        (workload_id, tenant_id, workload_id, template, "running", now),
                    )
                    operation_id = str(uuid.uuid4())
                    idempotency_key = f"reference-lab:{REFERENCE_LAB_REVISION}:{tenant_id}:{template}:deploy"
                    db.execute(
                        """INSERT OR IGNORE INTO operations
                           (id,user_id,tenant_id,workload_id,action,status,idempotency_key,fingerprint,created,error)
                           VALUES(?,?,?,?,?,'queued',?,?,?,NULL)""",
                        (
                            operation_id,
                            admin_id,
                            tenant_id,
                            workload_id,
                            "deploy",
                            idempotency_key,
                            idempotency_key,
                            now,
                        ),
                    )
            audit(db, admin_id, None, "reference_lab.provisioned", "college,hospital")


def audit(db, actor, tenant, action, resource=None, outcome="accepted"):
    db.execute("INSERT INTO audit(at,actor,tenant_id,action,resource,outcome) VALUES(?,?,?,?,?,?)",
               (time.time(), actor, tenant, action, resource, outcome))
