"""Authenticated management API. Queued intent is never reported as deployment success."""
from dataclasses import dataclass
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import logging
from pathlib import Path
import secrets
import sqlite3
import threading
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

from .catalog import catalog_response, stack_definition
from .store import Store, audit
from .detection import (
    DenialBurstBaseline,
    EdgeFrequencyDetectionPipeline,
    FlowRecord,
    TemporalGraphDetectionPipeline,
)
from .detection.temporal_graph import WorkloadDescriptor
from .infrastructure import InfrastructureUnavailable
from .infrastructure.kubernetes import KubernetesInfrastructure
from .lab import LabService
from .retail import RetailStore, create_retail_router
from .retail.accounts import AccountStore
from .telemetry import HubbleJsonFileCollector, IdentityIndex

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Settings:
    database: Path
    retail_database: Path | None = None
    marketplace: bool = False  # two shops + provider console with shared accounts
    origin: str = "https://localhost:8443"
    secure_cookie: bool = True
    session_seconds: int = 3600
    tenant_limit: int = 2
    infrastructure: Literal["disabled", "kubernetes"] = "disabled"
    kubeconfig: Path | None = None
    kube_api: str | None = None
    retail_manifest: Path | None = None
    hubble_export: Path | None = None
    temporal_model: Path | None = None

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
        if self.infrastructure not in {"disabled", "kubernetes"}:
            raise ValueError("Infrastructure must be disabled or kubernetes")
        if self.kube_api:
            kube_api = urlparse(self.kube_api)
            if (
                kube_api.scheme not in {"http", "https"}
                or kube_api.hostname not in {"127.0.0.1", "localhost"}
                or not kube_api.port
            ):
                raise ValueError("Kubernetes API override must be a loopback URL with a port")
        if self.temporal_model is not None:
            if self.temporal_model.is_symlink():
                raise ValueError("Temporal model must not be a symbolic link")
            model = self.temporal_model.resolve(strict=True)
            if model.suffix.lower() != ".pt" or not model.is_file():
                raise ValueError("Temporal model must be a regular .pt file")
            if model.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Temporal model exceeds the 10 MiB limit")
        if self.retail_manifest is not None:
            if self.retail_manifest.is_symlink():
                raise ValueError("Retail manifest must not be a symbolic link")
            manifest = self.retail_manifest.resolve(strict=True)
            if manifest.suffix.lower() not in {".yaml", ".yml"} or not manifest.is_file():
                raise ValueError("Retail manifest must be a regular YAML file")
            if manifest.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Retail manifest exceeds the 2 MiB limit")


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


class StackDeploy(Body):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,39}$")
    stack: Literal["retail-stack", "facilities-vendor-stack", "northstar-shop-stack", "bloom-shop-stack", "platform-stack"]


class Lifecycle(Body):
    confirmation: str = Field(min_length=3, max_length=40)
    expected_version: int = Field(ge=1)


class TrafficSimulate(Body):
    source_id: str = Field(min_length=1, max_length=100)
    destination_id: str = Field(min_length=1, max_length=100)
    port: int = Field(ge=1, le=65535)



def flow_evidence(flow) -> dict:
    """Incident evidence for one resolved flow, in the same shape as Store.get_normalized_traffic."""
    allowed = flow.verdict == "forwarded"
    cross = flow.source.tenant_id != flow.destination.tenant_id
    return {
        "id": flow.event_id, "at": flow.observed_at,
        "sourceId": flow.source.workload_id, "destinationId": flow.destination.workload_id,
        "sourceName": flow.source.workload_name, "destinationName": flow.destination.workload_name,
        "sourceTenant": flow.source.tenant_id, "destinationTenant": flow.destination.tenant_id,
        "port": flow.destination_port or 1, "decision": "allowed" if allowed else "denied",
        "reason": "cross-tenant" if cross else "approved-intent" if allowed else "default-deny",
    }


def _safely(function, *args):
    try:
        function(*args)
    except Exception:  # pragma: no cover - startup best effort
        logger.exception("Startup task %s failed", getattr(function, "__name__", function))


def create_app(settings: Settings) -> FastAPI:
    infrastructure = (
        KubernetesInfrastructure(
            settings.kubeconfig,
            api_server=settings.kube_api,
            retail_manifest=settings.retail_manifest,
        )
        if settings.infrastructure == "kubernetes"
        else None
    )
    store = Store(settings.database, infrastructure=infrastructure)
    retail_database = settings.retail_database or settings.database.with_name(
        f"{settings.database.stem}-retail{settings.database.suffix or '.sqlite'}"
    )
    retail_store = RetailStore(retail_database)
    detector = DenialBurstBaseline(window_seconds=60.0, denial_threshold=3)
    graph_detector = (
        TemporalGraphDetectionPipeline(settings.temporal_model)
        if settings.temporal_model is not None
        else EdgeFrequencyDetectionPipeline(anomaly_threshold=0.6)
    )
    if isinstance(graph_detector, TemporalGraphDetectionPipeline):
        graph_detector.validate([
            WorkloadDescriptor(**item) for item in store.detection_workloads()
        ], store.approved_edges())
    stop_reconciler = threading.Event()
    telemetry_status = {
        "enabled": settings.hubble_export is not None,
        "accepted": 0,
        "rejected": 0,
        "last_poll": None,
        "last_error": None,
        "findings": 0,
        "detector": getattr(graph_detector, "model_version", "edge-frequency-v1"),
    }
    collector = (
        HubbleJsonFileCollector(
            settings.hubble_export,
            lambda: IdentityIndex(store.workload_identities()),
        )
        if settings.hubble_export is not None
        else None
    )

    lab_service = LabService(store, infrastructure, telemetry_status)
    if infrastructure is not None and settings.marketplace:
        # Background shoppers browse both storefronts (web -> order API -> database), like real
        # traffic. The temporal model learns "normal" from these approved flows; without any
        # benign history before an attack it has nothing to compare against.
        def browse_loop():
            import urllib.request
            while True:
                for url in ("http://127.0.0.1:8094/api/resources/products", "http://127.0.0.1:8095/api/resources/products"):
                    try:
                        urllib.request.urlopen(url, timeout=3).read()
                    except Exception:
                        pass
                time.sleep(4)
        threading.Thread(target=browse_loop, name="background-shoppers", daemon=True).start()
    if infrastructure is not None:  # always start protected, even if a demo left SecureCloud off
        threading.Thread(target=lambda: _safely(lab_service.set_protection, True), name='protect-on-start', daemon=True).start()

    def reconcile_loop():
        while not stop_reconciler.is_set():
            try:
                store.reconcile_operations()
                store.reconcile_stack_operations()
                store.reconcile_containment_requests()
            except Exception:
                logger.exception("Infrastructure reconciliation iteration failed")
            stop_reconciler.wait(2.0)

    analysis_state = {"pending": False, "last": 0.0}

    def telemetry_loop():
        """Ingest Hubble flows continuously. Analysis runs in its own thread, so a slow model
        pass never delays the flow records the lab and the console are waiting for."""
        while not stop_reconciler.is_set():
            try:
                batch = collector.poll()
                inserted = store.ingest_normalized_flows(list(batch.flows))
                analysis_state["pending"] = analysis_state["pending"] or bool(inserted)
                telemetry_status.update(
                    accepted=telemetry_status["accepted"] + inserted,
                    rejected=telemetry_status["rejected"] + batch.rejected_count,
                    last_poll=time.time(),
                    last_error=None,
                )
            except Exception as exc:
                telemetry_status.update(last_poll=time.time(), last_error=type(exc).__name__)
                logger.warning("Hubble telemetry poll failed: %s", type(exc).__name__)
            stop_reconciler.wait(0.25)

    def analysis_loop():
        """Score the recent graph at most every 3 s; detection pauses while SecureCloud is off."""
        while not stop_reconciler.is_set():
            stop_reconciler.wait(0.5)
            if not (analysis_state["pending"] and time.time() - analysis_state["last"] >= 3.0 and lab_service.protection):
                continue
            analysis_state.update(pending=False, last=time.time())
            new_findings = 0
            try:
                # Only the analysis window is needed: a time-bounded query, not the newest 100k rows.
                recent_flows = store.get_normalized_flows(start=time.time() - 330, limit=100_000)
                if recent_flows:
                    application_events = retail_store.events(
                        limit=1_000,
                        start=recent_flows[0].observed_at - 5,
                        end=recent_flows[-1].observed_at + 5,
                    )
                    store.correlate_application_events(application_events)
                if recent_flows:
                    analysis_cutoff = recent_flows[-1].observed_at - 300
                    recent_flows = [
                        flow
                        for flow in recent_flows
                        if flow.observed_at >= analysis_cutoff
                    ]
                arguments = [
                    recent_flows,
                    store.approved_edges(),
                ]
                if isinstance(graph_detector, TemporalGraphDetectionPipeline):
                    arguments.append([
                        WorkloadDescriptor(**item)
                        for item in store.detection_workloads()
                    ])
                findings = graph_detector.analyze(*arguments)
                if isinstance(graph_detector, TemporalGraphDetectionPipeline):
                    store.record_risk_observations(graph_detector.last_observations)
                evidence_by_id = {
                    event["id"]: event
                    for event in store.get_normalized_traffic(limit=1_000, window_seconds=600)
                }
                flows_by_id = {flow.event_id: flow for flow in recent_flows}
                for finding in findings:
                    evidence = [
                        evidence_by_id[event_id]
                        for event_id in finding.event_ids
                        if event_id in evidence_by_id
                    ]
                    if not evidence:  # e.g. a volume spike on an approved path: allowed flows only
                        evidence = [flow_evidence(flows_by_id[event_id]) for event_id in finding.event_ids[:50] if event_id in flows_by_id]
                    if evidence and store.record_detection_finding(finding, evidence):
                        new_findings += 1
                telemetry_status.update(findings=telemetry_status["findings"] + new_findings)
            except Exception:
                logger.exception("Graph analysis failed")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        threads = []
        if infrastructure is not None:
            threads.append(
                threading.Thread(
                    target=reconcile_loop,
                    name="securecloud-reconciler",
                    daemon=True,
                ),
            )
        if collector is not None:
            threads.extend([
                threading.Thread(target=telemetry_loop, name="securecloud-telemetry", daemon=True),
                threading.Thread(target=analysis_loop, name="securecloud-analysis", daemon=True),
            ])
        application.state.background_threads = threads
        for thread in threads:
            thread.start()
        try:
            yield
        finally:
            stop_reconciler.set()
            for thread in threads:
                thread.join(timeout=5)

    app = FastAPI(
        title="SecureCloud API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.retail_store = retail_store
    app.state.detector = detector
    app.state.graph_detector = graph_detector
    app.state.settings = settings
    app.state.infrastructure = infrastructure
    app.state.telemetry_status = telemetry_status
    hasher = PasswordHasher()
    dummy_hash = hasher.hash(secrets.token_urlsafe(32))
    cookie = "__Host-securecloud" if settings.secure_cookie else "securecloud_dev"
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(settings.origin).hostname])

    @app.middleware("http")
    async def boundaries(request, call_next):
        # Caller-provided identity/correlation headers are never trusted. The
        # monolith creates a fresh request ID and passes identity internally
        # from its authenticated server-side session.
        blocked = {
            b"x-request-id",
            b"x-securecloud-tenant",
            b"x-securecloud-actor-ref",
            b"x-securecloud-session-ref",
        }
        request_id = str(uuid.uuid4())
        request.scope["headers"] = [
            (name, value)
            for name, value in request.scope["headers"]
            if name.lower() not in blocked
        ] + [(b"x-request-id", request_id.encode("ascii"))]
        request.state.request_id = request_id
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
            "X-Request-ID": request_id,
        })
        return response

    @app.exception_handler(RequestValidationError)
    def invalid(request, exc):
        return JSONResponse({"detail": "Validation error"}, status_code=422)

    @app.exception_handler(HTTPException)
    def generic(request, exc):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    common = dict(secure_cookie=settings.secure_cookie, session_seconds=settings.session_seconds,
                  correlation_store=store, lab=lab_service)
    if settings.marketplace:
        accounts = AccountStore(retail_database.with_name(f"{retail_database.stem}-accounts.sqlite"))
        bloom_store = RetailStore(retail_database.with_name(f"{retail_database.stem}-bloom.sqlite"), order_prefix="BL", tenant_id="bloom")
        app.state.accounts, app.state.bloom_store = accounts, bloom_store
        app.include_router(create_retail_router(retail_store, accounts=accounts, shop_id="northstar", prefix="/api/retail",
                                                mode="shop", mirror_upstream="http://127.0.0.1:8094", **common))
        app.include_router(create_retail_router(bloom_store, accounts=accounts, shop_id="bloom", prefix="/api/bloom",
                                                mode="shop", mirror_upstream="http://127.0.0.1:8095", **common))
        app.include_router(create_retail_router(retail_store, accounts=accounts, shop_id="securecloud", prefix="/api/provider",
                                                mode="provider", **common))
    else:
        app.include_router(create_retail_router(retail_store, **common))

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

    def stack_idem(request, user, db, fingerprint):
        key = request.headers.get("idempotency-key", "")
        if not 8 <= len(key) <= 100 or not key.isascii() or not key.isprintable():
            raise HTTPException(
                422, "Supply an Idempotency-Key of 8-100 printable ASCII characters"
            )
        old = db.execute(
            "SELECT * FROM stack_operations "
            "WHERE user_id=? AND idempotency_key=?",
            (user["user_id"], key),
        ).fetchone()
        if old and old["fingerprint"] != fingerprint:
            raise HTTPException(409, "Idempotency key was used for another request")
        return key, dict(old) if old else None

    @app.get("/api/health")
    def health():
        if infrastructure is None:
            return {
                "service": "securecloud",
                "infrastructure": {"connected": False, "provider": "disabled"},
                "telemetry": dict(telemetry_status),
            }
        try:
            state = infrastructure.health()
        except InfrastructureUnavailable:
            state = {"connected": False, "provider": "kubernetes", "state": "inconclusive"}
        return {
            "service": "securecloud",
            "infrastructure": state,
            "telemetry": dict(telemetry_status),
        }

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
        deployable: set[str] = set()
        if infrastructure is not None:
            deployable.update({"facilities-vendor-stack", "northstar-shop-stack", "bloom-shop-stack", "platform-stack"})
            if settings.retail_manifest is not None:
                deployable.add("retail-stack")
        return catalog_response(frozenset(deployable))

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

    @app.get("/api/tenants/{tenant}/stacks")
    def stacks(tenant: str, request: Request):
        user = session(request)
        with store.connect() as db:
            authorize(db, user, tenant)
            rows = db.execute(
                "SELECT * FROM stack_deployments WHERE tenant_id=? "
                "AND desired!='deleted' ORDER BY created",
                (tenant,),
            ).fetchall()
            return [dict(row) for row in rows]

    @app.post("/api/tenants/{tenant}/stacks", status_code=202)
    def deploy_stack(tenant: str, body: StackDeploy, request: Request):
        user = session(request, True)
        definition = stack_definition(body.stack)
        if definition is None:
            raise HTTPException(422, "Unknown stack")
        fingerprint = sha256(
            json.dumps(
                [tenant, "stack.deploy", body.model_dump()], sort_keys=True
            ).encode()
        ).hexdigest()
        with store.connect() as db:
            authorize(db, user, tenant, write=True)
            if infrastructure is None:
                raise HTTPException(503, "Stack infrastructure is not configured")
            if body.stack == "retail-stack" and settings.retail_manifest is None:
                raise HTTPException(503, "Retail stack manifest is not configured")
            key, old = stack_idem(request, user, db, fingerprint)
            if old:
                return old
            existing_count = db.execute(
                "SELECT count(*) FROM workloads "
                "WHERE tenant_id=? AND observed!='deleted'",
                (tenant,),
            ).fetchone()[0]
            if existing_count + len(definition.services) > 12:
                raise HTTPException(
                    409, "Stack exceeds the tenant workload quota"
                )
            deployment_id = str(uuid.uuid4())
            operation_id = str(uuid.uuid4())
            now = time.time()
            try:
                db.execute(
                    """INSERT INTO stack_deployments
                       (id,tenant_id,name,stack_id,desired,observed,created)
                       VALUES(?,?,?,?,?,'pending',?)""",
                    (
                        deployment_id,
                        tenant,
                        body.name,
                        body.stack,
                        "running",
                        now,
                    ),
                )
                for component in definition.services:
                    db.execute(
                        """INSERT INTO workloads
                           (id,tenant_id,name,template,desired,observed,created,
                            stack_deployment_id)
                           VALUES(?,?,?,?,?,'pending',?,?)""",
                        (
                            str(uuid.uuid4()),
                            tenant,
                            component.id,
                            component.template,
                            "running",
                            now,
                            deployment_id,
                        ),
                    )
                operation = {
                    "id": operation_id,
                    "user_id": user["user_id"],
                    "tenant_id": tenant,
                    "stack_deployment_id": deployment_id,
                    "action": "deploy",
                    "status": "queued",
                    "idempotency_key": key,
                    "fingerprint": fingerprint,
                    "created": now,
                    "error": None,
                }
                db.execute(
                    """INSERT INTO stack_operations
                       VALUES(:id,:user_id,:tenant_id,:stack_deployment_id,
                              :action,:status,:idempotency_key,:fingerprint,
                              :created,:error)""",
                    operation,
                )
                audit(
                    db,
                    user["user_id"],
                    tenant,
                    "stack.deploy.requested",
                    deployment_id,
                )
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Stack name or type already exists")
            return operation

    @app.get("/api/tenants/{tenant}/stack-operations/{operation}")
    def stack_operation(tenant: str, operation: str, request: Request):
        user = session(request)
        with store.connect() as db:
            authorize(db, user, tenant)
            row = db.execute(
                "SELECT * FROM stack_operations WHERE id=? AND tenant_id=?",
                (operation, tenant),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Stack operation not found")
            return dict(row)

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
        try:
            store.request_containment(incident_id, "quarantine", user["user_id"])
            store.reconcile_containment_requests()
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            raise HTTPException(status, str(exc))
        result = store.get_containment_request(incident_id)
        if result["status"] != "succeeded":
            raise HTTPException(503, result["error"] or "Containment has not been verified")
        return {"status": "quarantined", "verified": True}

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
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            raise HTTPException(status, str(exc))
        return {"status": "review"}

    @app.post("/api/incidents/{incident_id}/restore")
    def restore_incident(incident_id: str, request: Request):
        user = session(request, True)
        with store.connect() as db:
            authorize_incident(db, user, incident_id, write=True)
        try:
            store.request_containment(incident_id, "restore", user["user_id"])
            store.reconcile_containment_requests()
        except ValueError as exc:
            status = 404 if "not found" in str(exc).lower() else 409
            raise HTTPException(status, str(exc))
        result = store.get_containment_request(incident_id)
        if result["status"] != "succeeded":
            raise HTTPException(503, result["error"] or "Restore has not been verified")
        return {"status": "restored", "verified": True}

    @app.post("/api/demo/load")
    def load_demo(request: Request):
        user = session(request, True)
        if not user["administrator"]:
            raise HTTPException(403, "Administrator access required")
        if settings.infrastructure == "kubernetes":
            store.provision_reference_lab(user["user_id"])
            return {"status": "provisioning"}
        store.seed_demo_data(user["user_id"])
        return {"status": "loaded"}

    @app.get("/api/state")
    def get_state(request: Request):
        user = session(request)
        # Read through Store before opening the tenant query transaction; Store
        # methods own their connections and SQLite rejects nested write locks.
        recorded_traffic = store.get_traffic(limit=100)
        live_traffic = store.get_normalized_traffic(limit=100)
        merged_traffic = sorted(
            [*recorded_traffic, *live_traffic],
            key=lambda event: (event["at"], event["id"]),
        )
        distinct_traffic = {}
        for event in merged_traffic:
            key = (
                event["sourceId"], event["destinationId"], event["port"],
                event["decision"], event["reason"],
            )
            distinct_traffic[key] = event
        all_traffic = list(distinct_traffic.values())[-100:]
        all_incidents = store.get_incidents()
        all_risk = store.risk_observations()
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
                    "desired": r["desired"],
                    "quarantined": bool(r["quarantined"]),
                    "version": r["version"],
                    "kubernetesUid": r["kubernetes_uid"],
                    "kubernetesVersion": r["kubernetes_version"],
                    "createdAt": r["created"],
                    "previewUrl": (
                        "http://127.0.0.1:8091/"
                        if r["id"] == "college-web" and r["observed"] == "running"
                        else "http://127.0.0.1:8092/"
                        if r["id"] == "hospital-web" and r["observed"] == "running"
                        else "http://127.0.0.1:8094/"
                        if r["stack_deployment_id"] is not None
                        and r["name"] in ("frontend", "northstar-web")
                        and r["observed"] == "running"
                        else "http://127.0.0.1:8095/"
                        if r["stack_deployment_id"] is not None
                        and r["name"] in ("vendor-web", "bloom-web")
                        and r["observed"] == "running"
                        else None
                    ),
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
            risk = [
                observation
                for observation in all_risk
                if observation["tenantId"] in visible
            ]
            return {
                "version": 2,
                "tenants": tenants,
                "demoLoaded": len(tenants) >= 2,
                "workloads": workloads,
                "traffic": traffic,
                "incidents": incidents,
                "security": {
                    "detector": telemetry_status["detector"],
                    "telemetryEnabled": telemetry_status["enabled"],
                    "lastPoll": telemetry_status["last_poll"],
                    "observations": risk,
                },
            }

    return app
