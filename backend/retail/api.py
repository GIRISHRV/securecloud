from __future__ import annotations

from hashlib import sha256
import secrets
import sqlite3
import time
from typing import Literal

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from .mirror import mirror_in_background, mirror_order
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .accounts import local_profile
from .store import RetailError, RetailStore


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Registration(Body):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=14, max_length=256)
    display_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(default="", max_length=24)
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    model_config = ConfigDict(extra="forbid")


class CartItem(Body):
    product_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=20)


class CartQuantity(Body):
    quantity: int = Field(ge=1, le=20)


class Checkout(Body):
    recipient: str = Field(min_length=2, max_length=100)
    line1: str = Field(min_length=3, max_length=160)
    line2: str = Field(default="", max_length=160)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    postal_code: str = Field(pattern=r"^[A-Za-z0-9 -]{3,12}$")
    phone: str = Field(pattern=r"^[+0-9() .-]{7,24}$")


class Product(Body):
    sku: str = Field(pattern=r"^[A-Z0-9][A-Z0-9-]{2,39}$")
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=2, max_length=500)
    price_minor: int = Field(ge=0, le=100_000_000)
    currency: Literal["INR"] = "INR"
    stock_quantity: int = Field(ge=0, le=1_000_000)
    published: bool = True
    image_path: str = Field(default="", max_length=240)


class ProductUpdate(Body):
    sku: str | None = Field(default=None, pattern=r"^[A-Z0-9][A-Z0-9-]{2,39}$")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, min_length=2, max_length=500)
    price_minor: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: Literal["INR"] | None = None
    stock_quantity: int | None = Field(default=None, ge=0, le=1_000_000)
    published: bool | None = None
    image_path: str | None = Field(default=None, max_length=240)


class OrderStatus(Body):
    status: Literal["placed", "processing", "packing", "shipped", "delivered", "cancelled"]


class LabProtection(Body):
    enabled: bool


class LabRunRequest(Body):
    scenario_id: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9-]+$")


def create_retail_router(
    store: RetailStore, *, secure_cookie: bool, session_seconds: int,
    correlation_store=None,
    lab=None,
    accounts=None,
    shop_id: str = "northstar",
    prefix: str = "/api/retail",
    mode: str = "all",
    mirror_upstream: str | None = None,
) -> APIRouter:
    """One shop's API (mode="shop"), the provider console (mode="provider"), or both (legacy "all").

    With ``accounts`` set, sign-in uses the shared account store: one login works on every
    shop, and roles are granted per shop (owner) or for the provider console (provider).
    """
    router = APIRouter(prefix=prefix, tags=[f"{shop_id}-{mode}"])
    accounts = accounts or store
    shared = accounts is not store
    hasher = PasswordHasher()
    dummy_hash = hasher.hash(secrets.token_urlsafe(32))
    cookie = "__Host-retail" if secure_cookie else "retail_dev"
    attempts: dict[str, list[float]] = {}

    def public_user(user):
        return {
            "id": user.get("user_id", user.get("id")),
            **{key: user[key] for key in ("tenant_id", "email", "display_name", "phone", "role", "status") if key in user},
        }

    def resolve(token):
        row = accounts.resolve_session(token) if token else None
        if not row or not shared:
            return row
        granted = accounts.role(row["user_id"], shop_id)
        role = "owner" if granted == ("provider" if mode == "provider" else "owner") else "customer"
        if mode == "provider":
            return dict(row, role=role, tenant_id=shop_id)
        return dict(row, user_id=local_profile(store, row, role), role=role, tenant_id=store.tenant_id)

    def session(request: Request, mutate=False, owner=False):
        token = request.cookies.get(cookie)
        row = resolve(token)
        if not row:
            raise HTTPException(401, "Sign in to access the retail application")
        if mutate and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"]):
            raise HTTPException(403, "CSRF verification failed")
        if owner and row["role"] != "owner":
            raise HTTPException(403, "Shop-owner access required")
        return dict(row, token_digest=sha256(token.encode()).hexdigest())

    def request_key(request: Request):
        value = request.headers.get("idempotency-key", "")
        if not 8 <= len(value) <= 100 or not value.isascii() or not value.isprintable():
            raise HTTPException(422, "Supply an Idempotency-Key of 8-100 printable ASCII characters")
        return value

    def trusted_request_id(request: Request) -> str:
        value = getattr(request.state, "request_id", None)
        if not isinstance(value, str):
            raise HTTPException(500, "Request context unavailable")
        return value

    def security_scope(owner) -> set[str]:
        if correlation_store is None:
            return {owner["tenant_id"]}
        return correlation_store.retail_security_scope(owner["tenant_id"])

    def authorize_security_incident(owner, incident_id: str):
        if correlation_store is None:
            raise HTTPException(503, "Security plane unavailable")
        incident = next(
            (item for item in correlation_store.get_incidents() if item["id"] == incident_id),
            None,
        )
        if not incident or incident["tenantId"] not in security_scope(owner):
            raise HTTPException(404, "Incident not found")
        return incident

    @router.post("/auth/register", status_code=201)
    def register(body: Registration):
        try:
            return {"user": public_user(accounts.create_user(body.email, body.password, body.display_name, phone=body.phone))}
        except sqlite3.IntegrityError:
            raise HTTPException(409, "An account with that email already exists")
        except RetailError as exc:
            raise HTTPException(422, str(exc))

    @router.post("/auth/login")
    def login(body: Login, request: Request, response: Response):
        key, now = body.email.strip().lower(), time.time()
        recent = [stamp for stamp in attempts.get(key, []) if stamp >= now - 60]
        if len(recent) >= 8:
            raise HTTPException(429, "Too many sign-in attempts; try again later")
        record = accounts.authentication_record(body.email)
        try:
            valid = hasher.verify(record["password_digest"] if record else dummy_hash, body.password)
        except VerificationError:
            valid = False
        if not record or not valid or record["status"] != "active":
            if len(attempts) > 1_000:
                attempts.clear()
            recent.append(now)
            attempts[key] = recent
            raise HTTPException(401, "Invalid email or password")
        attempts.pop(key, None)
        token, csrf, session_id = accounts.create_session(record["id"], session_seconds, request.headers.get("user-agent", "")[:160])
        response.set_cookie(cookie, token, httponly=True, secure=secure_cookie, samesite="strict", max_age=session_seconds, path="/")
        return {"user": public_user(resolve(token)), "csrf": csrf, "session_id": session_id}

    @router.get("/auth/session")
    def read_session(request: Request):
        user = session(request)
        return {"user": public_user(user), "csrf": user["csrf"], "session_id": user["id"]}

    @router.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response):
        user = session(request, mutate=True)
        accounts.revoke_session(user["token_digest"])
        response.delete_cookie(cookie, path="/", secure=secure_cookie, httponly=True, samesite="strict")

    @router.get("/products")
    def products():
        return {"items": store.products()}

    @router.get("/products/{product_id}")
    def product(product_id: str):
        item = store.product(product_id)
        if not item:
            raise HTTPException(404, "Product not found")
        return item

    @router.get("/cart")
    def cart(request: Request):
        user = session(request)
        return store.cart(user["user_id"])

    @router.post("/cart/items")
    def add_cart_item(body: CartItem, request: Request):
        user = session(request, mutate=True)
        try:
            return store.set_cart_item(user["user_id"], body.product_id, body.quantity)
        except RetailError as exc:
            raise HTTPException(409, str(exc))

    @router.patch("/cart/items/{product_id}")
    def update_cart_item(product_id: str, body: CartQuantity, request: Request):
        user = session(request, mutate=True)
        try:
            return store.set_cart_item(user["user_id"], product_id, body.quantity)
        except RetailError as exc:
            raise HTTPException(409, str(exc))

    @router.delete("/cart/items/{product_id}")
    def delete_cart_item(product_id: str, request: Request):
        user = session(request, mutate=True)
        return store.remove_cart_item(user["user_id"], product_id)

    @router.post("/checkout", status_code=201)
    def checkout(body: Checkout, request: Request):
        user = session(request, mutate=True)
        address = body.model_dump()
        try:
            order = store.checkout(
                user, address, request_key(request), trusted_request_id(request), user["id"]
            )
        except RetailError as exc:
            raise HTTPException(409, str(exc))
        mirror_in_background(order, mirror_upstream)
        return order

    @router.get("/orders")
    def orders(request: Request):
        user = session(request)
        return {"items": store.orders(user["user_id"])}

    @router.get("/orders/{order_id}")
    def order(order_id: str, request: Request):
        user = session(request)
        item = store.order(order_id, user["user_id"])
        if not item:
            raise HTTPException(404, "Order not found")
        return item

    @router.get("/admin/overview")
    def admin_overview(request: Request):
        session(request, owner=True)
        return store.overview()

    @router.get("/admin/customers")
    def admin_customers(request: Request):
        session(request, owner=True)
        return {"items": store.customers()}

    @router.get("/admin/sessions")
    def admin_sessions(request: Request):
        session(request, owner=True)
        return {"items": store.sessions()}

    @router.get("/admin/products")
    def admin_products(request: Request):
        session(request, owner=True)
        return {"items": store.products(True)}

    @router.post("/admin/products", status_code=201)
    def create_product(body: Product, request: Request):
        session(request, mutate=True, owner=True)
        try:
            return store.save_product(body.model_dump())
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Product SKU already exists")

    @router.patch("/admin/products/{product_id}")
    def update_product(product_id: str, body: ProductUpdate, request: Request):
        session(request, mutate=True, owner=True)
        existing = store.product(product_id, True)
        if not existing:
            raise HTTPException(404, "Product not found")
        values = {
            key: existing[key]
            for key in (
                "sku", "name", "description", "price_minor", "currency",
                "stock_quantity", "published", "image_path",
            )
        }
        values.update(body.model_dump(exclude_unset=True))
        try:
            item = store.save_product(values, product_id)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Product SKU already exists")
        return item

    @router.get("/admin/orders")
    def admin_orders(request: Request):
        session(request, owner=True)
        return {"items": store.orders()}

    @router.get("/admin/orders/{order_id}")
    def admin_order(order_id: str, request: Request):
        session(request, owner=True)
        item = store.order(order_id)
        if not item:
            raise HTTPException(404, "Order not found")
        return item

    @router.patch("/admin/orders/{order_id}/status")
    def change_order_status(order_id: str, body: OrderStatus, request: Request):
        owner = session(request, mutate=True, owner=True)
        try:
            item = store.update_order_status(
                order_id, body.status, owner, trusted_request_id(request), owner["id"]
            )
        except RetailError as exc:
            raise HTTPException(409, str(exc))
        if not item:
            raise HTTPException(404, "Order not found")
        return item

    @router.get("/admin/activity")
    def activity(request: Request):
        owner = session(request, owner=True)
        return {"items": store.events(tenant_id=owner["tenant_id"])}

    @router.get("/admin/security/summary")
    def security_summary(request: Request):
        owner = session(request, owner=True)
        events = store.events(limit=100, tenant_id=owner["tenant_id"])
        if correlation_store is None:
            return {
                "applicationEvents": [dict(event, correlation=None) for event in events],
                "incidents": [], "risk": [], "traffic": [],
            }
        correlation_store.correlate_application_events(events)
        correlations = correlation_store.application_flow_correlations(
            [event["id"] for event in events]
        )
        enriched_events = [
            dict(event, correlation=correlations.get(event["id"]))
            for event in events
        ]
        events_by_id = {event["id"]: event for event in enriched_events}
        scope = security_scope(owner)
        findings = {}
        for finding in correlation_store.detection_findings():
            current = findings.get(finding["incident_id"])
            # Show the strongest evidence: prefer a containment recommendation, then the highest risk.
            rank = (finding["response"] == "containment-recommended", finding["accumulated_risk"])
            if current is None or rank >= (current["response"] == "containment-recommended", current["accumulated_risk"]):
                findings[finding["incident_id"]] = finding
        incidents = []
        for incident in correlation_store.get_incidents():
            if incident["tenantId"] not in scope:
                continue
            references = sorted({
                reference
                for evidence in incident["evidence"]
                for reference in evidence.get("applicationEventRefs", [])
            })
            incidents.append(dict(
                incident,
                applicationEvents=[events_by_id[ref] for ref in references if ref in events_by_id],
                finding=findings.get(incident["id"]),
                containment=correlation_store.get_containment_request(incident["id"]),
            ))
        recorded = correlation_store.get_traffic(limit=200)
        live = correlation_store.get_normalized_traffic(limit=200, window_seconds=900)
        risk = [item for item in correlation_store.risk_observations() if item["tenantId"] in scope]
        traffic = [item for item in [*recorded, *live] if item["sourceTenant"] in scope][-200:]
        if mode == "provider" and lab is not None:  # show only the current demo session
            since = lab.session_start
            def last_activity(item):  # new evidence can attach to an incident opened before this session
                return max([item["createdAt"], *(e.get("at", 0) for e in item["evidence"]), *(t.get("at", 0) for t in item["trace"])])
            incidents = [i for i in incidents if last_activity(i) >= since or i["status"] in ("quarantined", "review")]
            risk = [r for r in risk if r["windowEnd"] >= since]
            traffic = [t for t in traffic if t["at"] >= since]
        return {"applicationEvents": enriched_events, "incidents": incidents, "risk": risk, "traffic": traffic}

    @router.post("/admin/security/incidents/{incident_id}/quarantine")
    def owner_quarantine(incident_id: str, request: Request):
        owner = session(request, mutate=True, owner=True)
        authorize_security_incident(owner, incident_id)
        related = [item for item in correlation_store.detection_findings() if item["incident_id"] == incident_id]
        finding = next((item for item in related if item["response"] == "containment-recommended"), related[0] if related else None)
        if not finding or finding["response"] != "containment-recommended":
            raise HTTPException(
                409,
                "Containment requires corroborated model and policy evidence",
            )
        try:
            correlation_store.request_containment(incident_id, "quarantine", owner["user_id"])
            correlation_store.reconcile_containment_requests()
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        result = correlation_store.get_containment_request(incident_id)
        if result["status"] != "succeeded":
            raise HTTPException(503, result["error"] or "Containment has not been verified")
        return {"status": "quarantined", "verified": True}

    @router.post("/admin/security/incidents/{incident_id}/review")
    def owner_review(incident_id: str, request: Request):
        owner = session(request, mutate=True, owner=True)
        authorize_security_incident(owner, incident_id)
        try:
            correlation_store.update_incident_status(
                incident_id,
                "review",
                {
                    "at": time.time(),
                    "title": "Review started",
                    "detail": "Shop owner is reviewing evidence; quarantine remains active.",
                },
                actor=owner["user_id"],
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"status": "review"}

    @router.post("/admin/security/incidents/{incident_id}/dismiss")
    def owner_dismiss(incident_id: str, request: Request):
        owner = session(request, mutate=True, owner=True)
        authorize_security_incident(owner, incident_id)
        try:
            correlation_store.update_incident_status(
                incident_id,
                "closed",
                {
                    "at": time.time(),
                    "title": "Alert dismissed",
                    "detail": "Shop owner reviewed the evidence and closed the alert without containment.",
                },
                actor=owner["user_id"],
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"status": "closed"}

    @router.post("/admin/security/incidents/{incident_id}/restore")
    def owner_restore(incident_id: str, request: Request):
        owner = session(request, mutate=True, owner=True)
        authorize_security_incident(owner, incident_id)
        try:
            correlation_store.request_containment(incident_id, "restore", owner["user_id"])
            correlation_store.reconcile_containment_requests()
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        result = correlation_store.get_containment_request(incident_id)
        if result["status"] != "succeeded":
            raise HTTPException(503, result["error"] or "Restore has not been verified")
        return {"status": "restored", "verified": True}

    if lab is not None and mode != "provider" and shop_id == "northstar":  # the lab drives Northstar orders only
        def lab_order(email="customer@test.com"):
            """Place one real Northstar order for the lab and send it through the cluster."""
            account = store.authentication_record(email)
            if not account:
                raise RetailError("The lab customer account does not exist; run the retail seed")
            user = dict(store.user(account["id"]), user_id=account["id"])
            product = next((p for p in store.products() if p["stock_quantity"] > 0), None)
            if product is None:
                raise RetailError("No product is in stock")
            store.set_cart_item(user["user_id"], product["id"], 1)
            address = {"recipient": user["display_name"], "line1": "1 Lab Street", "line2": "", "city": "Bengaluru",
                       "state": "Karnataka", "postal_code": "560001", "phone": user.get("phone") or "9999999999"}
            order = store.checkout(user, address, "lab-" + secrets.token_hex(8), "lab-" + secrets.token_hex(6), user["user_id"])
            return order, mirror_order(order, upstream=mirror_upstream)
        lab.order_hook = lab_order

    def require_lab():
        if lab is None:
            raise HTTPException(503, "The live lab is not configured")
        return lab

    @router.post("/admin/lab/reset")
    def lab_reset(request: Request):
        owner = session(request, mutate=True, owner=True)
        # Close open, uncontained alerts so the next attack opens a fresh incident; recorded in each trace.
        if correlation_store is not None:
            for incident in correlation_store.get_incidents():
                if incident["status"] == "alert" and incident["tenantId"] in security_scope(owner):
                    correlation_store.update_incident_status(
                        incident["id"], "closed",
                        {"at": time.time(), "title": "Closed by demo reset",
                         "detail": "The provider started a new demo session; this alert had no containment."},
                        actor=owner["user_id"],
                    )
        return require_lab().reset()

    @router.post("/admin/lab/protection")
    def lab_protection(body: LabProtection, request: Request):
        session(request, mutate=True, owner=True)
        from backend.lab import LabUnavailable
        try:
            return require_lab().set_protection(body.enabled)
        except LabUnavailable as exc:
            raise HTTPException(409, str(exc))

    @router.get("/admin/lab/status")
    def lab_status(request: Request):
        session(request, owner=True)
        return require_lab().status()

    @router.get("/admin/lab/scenarios")
    def lab_scenarios(request: Request):
        session(request, owner=True)
        return {"items": require_lab().scenarios()}

    @router.get("/admin/lab/runs")
    def lab_runs(request: Request):
        session(request, owner=True)
        return {"items": require_lab().runs()}

    @router.get("/admin/lab/runs/{run_id}")
    def lab_run(run_id: str, request: Request):
        session(request, owner=True)
        result = require_lab().run(run_id)
        if result is None:
            raise HTTPException(404, "Lab run not found")
        return result

    @router.post("/admin/lab/runs", status_code=202)
    def start_lab_run(body: LabRunRequest, request: Request):
        owner = session(request, mutate=True, owner=True)
        from backend.lab import LabUnavailable
        try:
            return require_lab().start(body.scenario_id, owner["email"])
        except KeyError:
            raise HTTPException(404, "Unknown lab scenario")
        except LabUnavailable as exc:
            raise HTTPException(409, str(exc))

    @router.post("/admin/demo/load")
    def load_catalog(request: Request):
        session(request, mutate=True, owner=True)
        items = store.seed_catalog()
        return {"items": items, "sample_orders": store.seed_sample_history()}

    @router.get("/admin/platform/services")
    def platform_services(request: Request):
        """Provider view: every shop, shared platform service and plugin, and what each may call."""
        session(request, owner=True)
        if correlation_store is None:
            raise HTTPException(503, "Security plane unavailable")
        from backend.catalog import PLATFORM_PROFILES, PLUGIN_PROFILES, stack_definition
        with correlation_store.connect() as db:
            rows = db.execute(
                """SELECT w.id,w.name,w.template,w.observed,w.quarantined,s.stack_id,t.name AS tenant
                   FROM workloads w JOIN stack_deployments s ON s.id=w.stack_deployment_id JOIN tenants t ON t.id=w.tenant_id
                   WHERE s.desired!='deleted' AND w.observed!='deleted'
                     AND s.stack_id IN ('northstar-shop-stack','bloom-shop-stack','platform-stack')
                   ORDER BY s.stack_id,w.name"""
            ).fetchall()
        platform = [row["name"] for row in rows if row["stack_id"] == "platform-stack"]
        items = []
        for row in rows:
            definition = stack_definition(row["stack_id"])
            service = next((svc for svc in definition.services if svc.id == row["name"]), None)
            calls = list(service.dependencies) if service else []
            if row["name"].endswith("-api") and row["name"] not in PLUGIN_PROFILES and row["stack_id"] != "platform-stack":
                calls += platform
            items.append({
                "id": row["id"], "name": row["name"], "tenant": row["tenant"], "stack": row["stack_id"],
                "kind": "plugin" if row["name"] in PLUGIN_PROFILES else "platform" if row["name"] in PLATFORM_PROFILES else "shop",
                "status": row["observed"], "quarantined": bool(row["quarantined"]), "calls": calls,
            })
        return {"items": items}

    provider_paths = (f"{prefix}/admin/security", f"{prefix}/admin/lab", f"{prefix}/admin/platform")
    if mode == "shop":
        router.routes[:] = [r for r in router.routes if not r.path.startswith(provider_paths)]
    elif mode == "provider":
        router.routes[:] = [r for r in router.routes if r.path.startswith(provider_paths + (f"{prefix}/auth",))]
    return router
