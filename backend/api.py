"""Authenticated management API. Queued intent is never reported as deployment success."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal
from urllib.parse import urlparse
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .store import Store, audit
from .detection import DenialBurstBaseline, FlowRecord

CATALOG = [
    dict(id="web", name="Web application", cpu=0.25, memory=128, port=80),
    dict(id="api", name="API service", cpu=0.5, memory=256, port=8080),
    dict(id="database", name="Database", cpu=0.5, memory=512, port=5432),
]


@dataclass(frozen=True)
class Settings:
    database: Path
    origin: str = "https://localhost:8443"
    secure_cookie: bool = True
    session_seconds: int = 3600
    tenant_limit: int = 2

    def __post_init__(self):
        parsed = urlparse(self.origin)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("Specify a complete portal origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid portal origin")
        if self.secure_cookie and parsed.scheme != "https":
            raise ValueError("Secure sessions require HTTPS")
        if not self.secure_cookie and parsed.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            raise ValueError("Insecure cookies are restricted to loopback development")
        if self.session_seconds <= 0 or self.tenant_limit <= 0:
            raise ValueError("Invalid session or tenant limits")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Body):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=256)
    model_config = ConfigDict(extra="forbid")  # Password whitespace is significant.


class TenantCreate(Body):
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=160)


class Membership(Body):
    user_id: str = Field(min_length=1, max_length=100)
    role: Literal["viewer", "operator", "admin"]


class Deploy(Body):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,39}$")
    template: Literal["web", "api", "database"]


class Lifecycle(Body):
    confirmation: str = Field(min_length=3, max_length=40)
    expected_version: int = Field(ge=1)


class TrafficSimulate(Body):
    source_id: str = Field(min_length=1, max_length=100)
    destination_id: str = Field(min_length=1, max_length=100)
    port: int = Field(ge=1, le=65535)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="SecureCloud API", docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(settings.database)
    detector = DenialBurstBaseline(window_seconds=60.0, denial_threshold=3)
    app.state.store = store
    app.state.detector = detector
    app.state.settings = settings
    hasher = PasswordHasher()
    dummy_hash = hasher.hash(secrets.token_urlsafe(32))
    cookie = "__Host-securecloud" if settings.secure_cookie else "securecloud_dev"
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(settings.origin).hostname])

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") != settings.origin.rstrip("/"):
                return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "JSON required"}, status_code=415)
            # Count actual received bytes rather than trusting Content-Length.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update({
            "Content-Security-Policy": "default-src 'self'",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        })
        return response

    @app.exception_handler(RequestValidationError)
    def invalid(request, exc):
        return JSONResponse({"detail": "Validation error"}, status_code=422)

    @app.exception_handler(HTTPException)
    def generic(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    def session(request: Request, mutate: bool = False):
        token = request.cookies.get(cookie)
        if not token:
            raise HTTPException(401, "Sign in to access the cloud management API")
        with store.connect() as db:
            row = db.execute(
                "SELECT s.csrf, u.id as user_id, u.username, u.administrator FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>? AND u.disabled=0",
                (sha256(token.encode()).hexdigest(), time.time())
            ).fetchone()
        if not row:
            raise HTTPException(401, "Session expired; sign in again")
        if mutate and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"]):
            raise HTTPException(403, "CSRF verification failed")
        return dict(row, token_hash=sha256(token.encode()).hexdigest())

    def authorize(db, user, tenant_id: str, write: bool = False):
        if user["administrator"]:
            return
        row = db.execute("SELECT role FROM memberships WHERE tenant_id=? AND user_id=?", (tenant_id, user["user_id"])).fetchone()
        if not row:
            raise HTTPException(404, "Tenant not found")
        if write and row["role"] not in {"operator", "admin"}:
            raise HTTPException(403, "Tenant access denied")

    def visible_tenant_ids(db, user) -> set[str]:
        if user["administrator"]:
            return {row["id"] for row in db.execute("SELECT id FROM tenants")}
        return {
            row["tenant_id"]
            for row in db.execute(
                "SELECT tenant_id FROM memberships WHERE user_id=?",
                (user["user_id"],),
            )
        }

    def authorize_incident(db, user, incident_id: str, write: bool = False):
        row = db.execute(
            "SELECT tenant_id FROM incidents WHERE id=?", (incident_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Incident not found")
        authorize(db, user, row["tenant_id"], write)

    def idem(request, user, db, fingerprint):
        key = request.headers.get("idempotency-key", "")
        if not 8 <= len(key) <= 100 or not key.isascii() or not key.isprintable():
            raise HTTPException(422, "Supply an Idempotency-Key of 8–100 printable ASCII characters")
        old = db.execute("SELECT * FROM operations WHERE user_id=? AND idempotency_key=?", (user["user_id"], key)).fetchone()
        if old and old["fingerprint"] != fingerprint:
            raise HTTPException(409, "Idempotency key was used for another request")
        return key, dict(old) if old else None

    def enqueue(db, user, tenant, workload, action, key, fingerprint):
        operation = dict(id=str(uuid.uuid4()), user_id=user["user_id"], tenant_id=tenant,
                         workload_id=workload, action=action, status="queued", idempotency_key=key,
                         fingerprint=fingerprint, created=time.time(), error=None)
        db.execute("INSERT INTO operations VALUES(:id,:user_id,:tenant_id,:workload_id,:action,:status,:idempotency_key,:fingerprint,:created,:error)", operation)
        audit(db, user["user_id"], tenant, f"workload.{action}.requested", workload)
        return operation

    @app.get("/api/health")
    def health():
        return {"service": "securecloud", "infrastructure": "not-connected"}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request, response: Response):
        now = time.time()
        ip = request.client.host if request.client else "unknown"
        with store.connect() as db:
            db.execute("DELETE FROM login_limits WHERE expires<=?", (now,))
            limited = False
            for scope, limit in ((f"ip:{ip}", 30), (f"user:{body.username.casefold()}", 8)):
                key = sha256(scope.encode()).hexdigest()
                db.execute("INSERT INTO login_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1", (key, now + 300))
                limited |= db.execute("SELECT attempts FROM login_limits WHERE key=?", (key,)).fetchone()[0] > limit
            user = db.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        if limited:
            raise HTTPException(429, "Too many sign-in attempts; try later")
        try:
            valid = hasher.verify(user["password_hash"] if user else dummy_hash, body.password)
        except VerificationError:
            valid = False
        if not valid or not user or user["disabled"]:
            raise HTTPException(401, "Invalid sign-in details")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            old = request.cookies.get(cookie, "")
            db.execute("DELETE FROM sessions WHERE token_hash=?", (sha256(old.encode()).hexdigest(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (sha256(token.encode()).hexdigest(), user["id"], csrf, now + settings.session_seconds))
            audit(db, user["id"], None, "session.created")
        response.set_cookie(cookie, token, httponly=True, secure=settings.secure_cookie,
                            samesite="strict", max_age=settings.session_seconds, path="/")
        return {"user": {"id": user["id"], "username": user["username"], "administrator": bool(user["administrator"])}, "csrf": csrf}

    @app.get("/api/auth/session")
    def whoami(request: Request):
        user = session(request)
        return {"user": {"id": user["user_id"], "username": user["username"], "administrator": bool(user["administrator"])}, "csrf": user["csrf"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        user = session(request, True)
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
            audit(db, user["user_id"], None, "session.revoked")
        response.delete_cookie(cookie, path="/", secure=settings.secure_cookie, httponly=True, samesite="strict")
        return {"signed_out": True}

    @app.get("/api/catalog")
    def catalog(request: Request):
        session(request)
        return CATALOG

    @app.get("/api/tenants")
    def tenants(request: Request):
        user = session(request)
        with store.connect() as db:
            if user["administrator"]:
                rows = db.execute("SELECT * FROM tenants ORDER BY created").fetchall()
            else:
                rows = db.execute("SELECT t.* FROM tenants t JOIN memberships m ON t.id=m.tenant_id WHERE m.user_id=? ORDER BY t.created", (user["user_id"],)).fetchall()
            return [dict(r) for r in rows]

    @app.post("/api/tenants", status_code=201)
    def create_tenant(body: TenantCreate, request: Request):
        user = session(request, True)
        if not user["administrator"]:
            raise HTTPException(403, "Administrator access required to provision tenants")
        tenant = str(uuid.uuid4())
        with store.connect() as db:
            if db.execute("SELECT count(*) FROM tenants").fetchone()[0] >= settings.tenant_limit:
                raise HTTPException(409, "Demonstrator tenant limit reached")
            try:
                db.execute("INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
                           (tenant, body.name, body.description, time.time()))
                db.execute("INSERT INTO memberships VALUES(?,?,?)", (tenant, user["user_id"], "admin"))
                audit(db, user["user_id"], tenant, "tenant.created", tenant)
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Tenant name already exists")
        return {"id": tenant, "name": body.name, "description": body.description}

    @app.put("/api/tenants/{tenant}/memberships")
    def membership(tenant: str, body: Membership, request: Request):
        user = session(request, True)
        with store.connect() as db:
            authorize(db, user, tenant, write=True)
            if not db.execute("SELECT 1 FROM tenants WHERE id=?", (tenant,)).fetchone():
                raise HTTPException(404, "Tenant not found")
            if not db.execute("SELECT 1 FROM users WHERE id=?", (body.user_id,)).fetchone():
                raise HTTPException(404, "User not found")
            db.execute("INSERT INTO memberships VALUES(?,?,?) ON CONFLICT(tenant_id,user_id) DO UPDATE SET role=excluded.role",
                       (tenant, body.user_id, body.role))
            audit(db, user["user_id"], tenant, "membership.updated", body.user_id)
        return {"status": "updated"}

    @app.get("/api/tenants/{tenant}/workloads")
    def workloads(tenant: str, request: Request):
        user = session(request)
        with store.connect() as db:
            authorize(db, user, tenant)
            rows = db.execute("SELECT * FROM workloads WHERE tenant_id=? AND observed!='deleted' ORDER BY created", (tenant,)).fetchall()
            return [dict(r) for r in rows]

    @app.post("/api/tenants/{tenant}/workloads", status_code=202)
    def deploy(tenant: str, body: Deploy, request: Request):
        user = session(request, True)
        fingerprint = sha256(json.dumps([tenant, "deploy", body.model_dump()], sort_keys=True).encode()).hexdigest()
        with store.connect() as db:
            authorize(db, user, tenant, write=True)
            key, old = idem(request, user, db, fingerprint)
            if old:
                return old
            if db.execute("SELECT count(*) FROM workloads WHERE tenant_id=? AND observed!='deleted'", (tenant,)).fetchone()[0] >= 12:
                raise HTTPException(409, "Workload quota reached")
            workload = str(uuid.uuid4())
            try:
                db.execute("INSERT INTO workloads(id,tenant_id,name,template,desired,created) VALUES(?,?,?,?,?,?)", (workload, tenant, body.name, body.template, "running", time.time()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Workload name already exists")
            return enqueue(db, user, tenant, workload, "deploy", key, fingerprint)

    @app.post("/api/tenants/{tenant}/workloads/{workload}/{action}", status_code=202)
    def lifecycle(tenant: str, workload: str, action: Literal["stop", "delete"], body: Lifecycle, request: Request):
        user = session(request, True)
        fingerprint = sha256(json.dumps([tenant, workload, action, body.model_dump()], sort_keys=True).encode()).hexdigest()
        with store.connect() as db:
            authorize(db, user, tenant, write=True)
            row = db.execute("SELECT * FROM workloads WHERE id=? AND tenant_id=?", (workload, tenant)).fetchone()
            if not row:
                raise HTTPException(404, "Workload not found")
            key, old = idem(request, user, db, fingerprint)
            if old:
                return old
            if body.confirmation != row["name"]:
                raise HTTPException(409, "Exact workload name required")
            if body.expected_version != row["version"]:
                raise HTTPException(409, "Workload changed; refresh before continuing")
            if action == "delete" and row["quarantined"]:
                raise HTTPException(409, "Quarantined workload cannot be deleted")
            if db.execute("SELECT 1 FROM operations WHERE workload_id=? AND status IN ('queued','running')", (workload,)).fetchone():
                raise HTTPException(409, "An operation is already in progress")
            db.execute("UPDATE workloads SET desired=?,version=version+1 WHERE id=?", ("stopped" if action == "stop" else "deleted", workload))
            return enqueue(db, user, tenant, workload, action, key, fingerprint)

    @app.get("/api/tenants/{tenant}/operations/{operation}")
    def operation(tenant: str, operation: str, request: Request):
        user = session(request)
        with store.connect() as db:
            authorize(db, user, tenant)
            row = db.execute("SELECT * FROM operations WHERE id=? AND tenant_id=?", (operation, tenant)).fetchone()
            if not row:
                raise HTTPException(404, "Operation not found")
            return dict(row)

    # --- Telemetry & Zero-Trust Enforcement Endpoints ---

    @app.post("/api/traffic/simulate")
    def simulate_traffic(body: TrafficSimulate, request: Request):
        user = session(request, True)
        now = time.time()
        with store.connect() as db:
            src = db.execute("SELECT * FROM workloads WHERE id=?", (body.source_id,)).fetchone()
            dst = db.execute("SELECT * FROM workloads WHERE id=?", (body.destination_id,)).fetchone()
            if not src or not dst:
                raise HTTPException(404, "Source or destination workload not found")
            if src["id"] == dst["id"]:
                raise HTTPException(400, "Choose two different workloads")
            authorize(db, user, src["tenant_id"], write=True)
            
            # Policy enforcement:
            # 1. Availability check
            if src["observed"] != "running" or dst["observed"] != "running":
                decision = "inconclusive"
                reason = "unavailable"
            # 2. Quarantine check
            elif src["quarantined"] or dst["quarantined"]:
                decision = "denied"
                reason = "quarantine"
            # 3. Cross-tenant check
            elif src["tenant_id"] != dst["tenant_id"]:
                decision = "denied"
                reason = "cross-tenant"
            # 4. Zero-trust intent check
            elif src["template"] == "web" and dst["template"] == "api" and body.port == 8080:
                decision = "allowed"
                reason = "approved-intent"
            elif src["template"] == "api" and dst["template"] == "database" and body.port == 5432:
                decision = "allowed"
                reason = "approved-intent"
            else:
                decision = "denied"
                reason = "default-deny"

            event_id = str(uuid.uuid4())
            event = {
                "id": event_id,
                "at": now,
                "sourceId": src["id"],
                "destinationId": dst["id"],
                "sourceName": src["name"],
                "destinationName": dst["name"],
                "sourceTenant": src["tenant_id"],
                "destinationTenant": dst["tenant_id"],
                "port": body.port,
                "decision": decision,
                "reason": reason,
            }
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

            # Deterministic comparison baseline; not the temporal-graph model.
            flow = FlowRecord(
                id=event_id,
                source_id=src["id"],
                destination_id=dst["id"],
                source_tenant=src["tenant_id"],
                destination_tenant=dst["tenant_id"],
                port=body.port,
                at=now,
                decision=decision,
                reason=reason,
            )
            score = detector.score_event(flow)
            detector.record_flow(flow)

            # If anomalous or burst denial, update or create incident
            active = db.execute("SELECT * FROM incidents WHERE source_id=? AND status!='restored'", (src["id"],)).fetchone()
            if active:
                if flow.decision == "denied":
                    evidence = json.loads(active["evidence_json"])
                    evidence.append(event)
                    db.execute("UPDATE incidents SET evidence_json=? WHERE id=?", (json.dumps(evidence), active["id"]))
            elif score.is_anomalous:
                # Collect recent evidence
                recent_events = [event]
                past_events = db.execute(
                    "SELECT * FROM traffic_events WHERE source_id=? AND at>=? ORDER BY at DESC LIMIT 10",
                    (src["id"], now - 60.0)
                ).fetchall()
                for pe in past_events:
                    if pe["id"] != event_id:
                        recent_events.append({
                            "id": pe["id"],
                            "at": pe["at"],
                            "sourceId": pe["source_id"],
                            "destinationId": pe["destination_id"],
                            "sourceName": pe["source_name"],
                            "destinationName": pe["destination_name"],
                            "sourceTenant": pe["source_tenant"],
                            "destinationTenant": pe["destination_tenant"],
                            "port": pe["port"],
                            "decision": pe["decision"],
                            "reason": pe["reason"],
                        })
                
                inc_id = str(uuid.uuid4())
                inc = {
                    "id": inc_id,
                    "sourceId": src["id"],
                    "sourceName": src["name"],
                    "tenantId": src["tenant_id"],
                    "status": "alert",
                    "reason": score.reasons[0],
                    "createdAt": now,
                    "evidence": recent_events,
                    "trace": [
                        {"at": now, "title": "Alert generated", "detail": score.reasons[0]}
                    ],
                }
                db.execute(
                    """INSERT INTO incidents
                       (id, source_id, source_name, tenant_id, status, reason, created_at, evidence_json, trace_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        inc["id"], inc["sourceId"], inc["sourceName"],
                        inc["tenantId"], inc["status"], inc["reason"],
                        inc["createdAt"], json.dumps(inc["evidence"]), json.dumps(inc["trace"])
                    )
                )
                audit(db, "system.detector", inc["tenantId"], "incident.created", inc["id"])

            return event

    @app.get("/api/traffic")
    def get_traffic(request: Request):
        user = session(request)
        with store.connect() as db:
            visible = visible_tenant_ids(db, user)
        return [event for event in store.get_traffic() if event["sourceTenant"] in visible]

    @app.get("/api/incidents")
    def get_incidents(request: Request):
        user = session(request)
        with store.connect() as db:
            visible = visible_tenant_ids(db, user)
        return [incident for incident in store.get_incidents() if incident["tenantId"] in visible]

    @app.get("/api/incidents/{incident_id}")
    def get_incident(incident_id: str, request: Request):
        user = session(request)
        with store.connect() as db:
            authorize_incident(db, user, incident_id)
        incidents = [i for i in store.get_incidents() if i["id"] == incident_id]
        if not incidents:
            raise HTTPException(404, "Incident not found")
        return incidents[0]

    @app.post("/api/incidents/{incident_id}/quarantine")
    def quarantine_incident(incident_id: str, request: Request):
        user = session(request, True)
        with store.connect() as db:
            authorize_incident(db, user, incident_id, write=True)
        now = time.time()
        trace_entry = {
            "at": now,
            "title": "Response: quarantined",
            "detail": "Simulated inbound and outbound traffic is now denied, including previously approved access.",
        }
        try:
            store.update_incident_status(incident_id, "quarantined", trace_entry, actor=user["user_id"])
        except ValueError:
            raise HTTPException(404, "Incident not found")
        return {"status": "quarantined"}

    @app.post("/api/incidents/{incident_id}/review")
    def review_incident(incident_id: str, request: Request):
        user = session(request, True)
        with store.connect() as db:
            authorize_incident(db, user, incident_id, write=True)
        now = time.time()
        trace_entry = {
            "at": now,
            "title": "Review started",
            "detail": "Operator is reviewing the evidence. Quarantine remains in place until restore.",
        }
        try:
            store.update_incident_status(incident_id, "review", trace_entry, actor=user["user_id"])
        except ValueError:
            raise HTTPException(404, "Incident not found")
        return {"status": "review"}

    @app.post("/api/incidents/{incident_id}/restore")
    def restore_incident(incident_id: str, request: Request):
        user = session(request, True)
        with store.connect() as db:
            authorize_incident(db, user, incident_id, write=True)
        now = time.time()
        trace_entry = {
            "at": now,
            "title": "Response: restored",
            "detail": "Quarantine removed. The original static tenant intents apply again.",
        }
        try:
            store.update_incident_status(incident_id, "restored", trace_entry, actor=user["user_id"])
        except ValueError:
            raise HTTPException(404, "Incident not found")
        return {"status": "restored"}

    @app.post("/api/demo/load")
    def load_demo(request: Request):
        user = session(request, True)
        if not user["administrator"]:
            raise HTTPException(403, "Administrator access required")
        store.seed_demo_data(user["user_id"])
        return {"status": "loaded"}

    @app.get("/api/state")
    def get_state(request: Request):
        user = session(request)
        # Read through Store before opening the tenant query transaction; Store
        # methods own their connections and SQLite rejects nested write locks.
        all_traffic = store.get_traffic(limit=100)
        all_incidents = store.get_incidents()
        with store.connect() as db:
            visible = visible_tenant_ids(db, user)
            tenants = [
                dict(r)
                for r in db.execute(
                    "SELECT id, name, description FROM tenants ORDER BY created"
                ).fetchall()
                if r["id"] in visible
            ]
            workloads = [
                {
                    "id": r["id"],
                    "tenantId": r["tenant_id"],
                    "templateId": r["template"],
                    "name": r["name"],
                    "status": r["observed"],
                    "quarantined": bool(r["quarantined"]),
                    "createdAt": r["created"],
                }
                for r in db.execute("SELECT * FROM workloads WHERE observed!='deleted' ORDER BY created").fetchall()
                if r["tenant_id"] in visible
            ]
            traffic = [
                event
                for event in all_traffic
                if event["sourceTenant"] in visible
            ]
            incidents = [
                incident
                for incident in all_incidents
                if incident["tenantId"] in visible
            ]
            return {
                "version": 2,
                "tenants": tenants,
                "demoLoaded": len(tenants) >= 2,
                "workloads": workloads,
                "traffic": traffic,
                "incidents": incidents,
            }

    return app
