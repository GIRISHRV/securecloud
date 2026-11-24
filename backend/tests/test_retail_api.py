import secrets
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api import Settings, create_app
from backend.retail import RetailStore
from backend.telemetry import NormalizedFlow, WorkloadIdentity


def make_lab(tmp_path):
    app = create_app(
        Settings(
            tmp_path / "securecloud.sqlite",
            retail_database=tmp_path / "retail.sqlite",
            origin="http://testserver",
            secure_cookie=False,
        )
    )
    owner_password = secrets.token_urlsafe(24)
    app.state.retail_store.create_user(
        "owner@example.com", owner_password, "Shop Owner", role="owner"
    )
    app.state.retail_store.seed_catalog()
    return app, owner_password


def client(app):
    return TestClient(app, headers={"Origin": "http://testserver"})


def login(api, email, password):
    response = api.post("/api/retail/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    api.headers["X-CSRF-Token"] = response.json()["csrf"]
    return response.json()


def register_alice(api, password):
    response = api.post(
        "/api/retail/auth/register",
        json={
            "email": "Alice@Example.com",
            "password": password,
            "display_name": "Alice Johnson",
            "phone": "+91 98765 43210",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["email"] == "alice@example.com"


def checkout_payload(line1="42 Lake View Road"):
    return {
        "recipient": "Alice Johnson",
        "line1": line1,
        "line2": "Apartment 3B",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "phone": "+91 98765 43210",
    }


def complete_order(api):
    products = api.get("/api/retail/products").json()["items"]
    backpack = next(product for product in products if product["sku"] == "NS-BAG-014")
    added = api.post(
        "/api/retail/cart/items",
        json={"product_id": backpack["id"], "quantity": 2},
    )
    assert added.status_code == 200, added.text
    assert added.json()["subtotal_minor"] == 299800
    return api.post(
        "/api/retail/checkout",
        json=checkout_payload(),
        headers={"Idempotency-Key": "alice-checkout-001"},
    )


def test_complete_customer_checkout_and_owner_visibility(tmp_path):
    app, owner_password = make_lab(tmp_path)
    alice, owner = client(app), client(app)
    alice_password = secrets.token_urlsafe(24)
    register_alice(alice, alice_password)
    alice_session = login(alice, "alice@example.com", alice_password)

    checkout = complete_order(alice)
    assert checkout.status_code == 201, checkout.text
    order = checkout.json()
    assert order["customer"]["name"] == "Alice Johnson"
    assert order["delivery_address"]["line1"] == "42 Lake View Road"
    assert order["payment"]["provider"] == "simulator"
    assert order["payment"]["status"] == "paid"
    assert order["items"][0]["sku_snapshot"] == "NS-BAG-014"
    assert order["items"][0]["quantity"] == 2
    assert alice.get("/api/retail/orders").json()["items"][0]["id"] == order["id"]

    owner_session = login(owner, "owner@example.com", owner_password)
    customers = owner.get("/api/retail/admin/customers").json()["items"]
    assert customers[0]["email"] == "alice@example.com"
    assert customers[0]["order_count"] == 1
    sessions = owner.get("/api/retail/admin/sessions").json()["items"]
    alice_active = next(item for item in sessions if item["email"] == "alice@example.com")
    assert alice_active["active"] is True
    assert alice_active["id"] == alice_session["session_id"]
    assert owner_session["user"]["role"] == "owner"
    assert owner.get("/api/retail/admin/orders").json()["items"][0]["id"] == order["id"]
    overview = owner.get("/api/retail/admin/overview").json()
    assert overview["orders_today"] == 1
    assert overview["revenue_today_minor"] == 299800


def test_checkout_is_idempotent_and_stock_changes_once(tmp_path):
    app, _ = make_lab(tmp_path)
    alice = client(app)
    password = secrets.token_urlsafe(24)
    register_alice(alice, password)
    login(alice, "alice@example.com", password)
    first = complete_order(alice)
    second = alice.post(
        "/api/retail/checkout",
        json=checkout_payload(),
        headers={"Idempotency-Key": "alice-checkout-001"},
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    backpack = app.state.retail_store.product("prod-backpack")
    assert backpack["stock_quantity"] == 30
    conflict = alice.post(
        "/api/retail/checkout",
        json=checkout_payload("Different address"),
        headers={"Idempotency-Key": "alice-checkout-001"},
    )
    assert conflict.status_code == 409


def test_customer_cannot_read_another_order_or_owner_endpoints(tmp_path):
    app, _ = make_lab(tmp_path)
    alice, bob = client(app), client(app)
    alice_password, bob_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    register_alice(alice, alice_password)
    assert bob.post(
        "/api/retail/auth/register",
        json={"email": "bob@example.com", "password": bob_password, "display_name": "Bob Rao"},
    ).status_code == 201
    login(alice, "alice@example.com", alice_password)
    order = complete_order(alice).json()
    login(bob, "bob@example.com", bob_password)
    assert bob.get(f"/api/retail/orders/{order['id']}").status_code == 404
    assert bob.get("/api/retail/admin/orders").status_code == 403


def test_csrf_role_and_order_transition_guards(tmp_path):
    app, owner_password = make_lab(tmp_path)
    alice, owner = client(app), client(app)
    password = secrets.token_urlsafe(24)
    register_alice(alice, password)
    login(alice, "alice@example.com", password)
    order = complete_order(alice).json()
    login(owner, "owner@example.com", owner_password)
    owner.headers["X-CSRF-Token"] = "wrong"
    assert owner.patch(
        f"/api/retail/admin/orders/{order['id']}/status", json={"status": "processing"}
    ).status_code == 403
    login(owner, "owner@example.com", owner_password)
    invalid = owner.patch(
        f"/api/retail/admin/orders/{order['id']}/status", json={"status": "shipped"}
    )
    assert invalid.status_code == 409
    valid = owner.patch(
        f"/api/retail/admin/orders/{order['id']}/status", json={"status": "processing"}
    )
    assert valid.status_code == 200
    assert valid.json()["status"] == "processing"
    assert owner.get("/api/retail/admin/activity").json()["items"][0]["action"] == "order.status_changed"


def test_explicit_catalog_loader_requires_owner(tmp_path):
    app, owner_password = make_lab(tmp_path)
    with app.state.retail_store.connect() as db:
        db.execute("DELETE FROM products")
    owner = client(app)
    login(owner, "owner@example.com", owner_password)
    loaded = owner.post("/api/retail/admin/demo/load", json={})
    assert loaded.status_code == 200
    assert len(loaded.json()["items"]) == 4


def test_sample_history_is_labelled_unusable_and_writes_no_security_events(tmp_path):
    app, owner_password = make_lab(tmp_path)
    store = app.state.retail_store
    events_before = len(store.events(limit=1_000))
    created = store.seed_sample_history(days=10, customers=5, seed=3)
    assert created > 0
    assert store.seed_sample_history(days=10, customers=5, seed=3) == 0
    with store.connect() as db:
        samples = db.execute("SELECT email FROM retail_users WHERE email LIKE '%@sample.northstar.test'").fetchall()
        orphan_items = db.execute(
            "SELECT COUNT(*) FROM orders o LEFT JOIN order_items i ON i.order_id=o.id WHERE i.id IS NULL"
        ).fetchone()[0]
    assert len(samples) == 5
    assert orphan_items == 0
    assert len(store.events(limit=1_000)) == events_before
    api = client(app)
    rejected = api.post(
        "/api/retail/auth/login",
        json={"email": samples[0]["email"], "password": owner_password},
    )
    assert rejected.status_code == 401
    owner = client(app)
    login(owner, "owner@example.com", owner_password)
    assert len(owner.get("/api/retail/admin/orders").json()["items"]) == created


def test_registration_and_payloads_fail_closed(tmp_path):
    app, _ = make_lab(tmp_path)
    api = client(app)
    password = secrets.token_urlsafe(24)
    register_alice(api, password)
    duplicate = api.post(
        "/api/retail/auth/register",
        json={"email": "alice@example.com", "password": password, "display_name": "Other Alice"},
    )
    assert duplicate.status_code == 409
    assert api.post(
        "/api/retail/auth/register",
        json={"email": "bad", "password": password, "display_name": "Bad", "role": "owner"},
    ).status_code == 422


def test_trusted_request_context_and_application_flow_correlation(tmp_path):
    app, owner_password = make_lab(tmp_path)
    alice, owner = client(app), client(app)
    alice_password = secrets.token_urlsafe(24)
    register_alice(alice, alice_password)
    alice_session = login(alice, "alice@example.com", alice_password)

    product = alice.get("/api/retail/products").json()["items"][0]
    assert alice.post(
        "/api/retail/cart/items",
        json={"product_id": product["id"], "quantity": 1},
    ).status_code == 200
    checkout = alice.post(
        "/api/retail/checkout",
        json=checkout_payload(),
        headers={
            "Idempotency-Key": "trusted-context-001",
            "X-Request-ID": "caller-controlled-request",
            "X-SecureCloud-Actor-Ref": "forged-actor",
            "X-SecureCloud-Session-Ref": "forged-session",
        },
    )
    assert checkout.status_code == 201, checkout.text
    trusted_request_id = checkout.headers["x-request-id"]
    assert trusted_request_id != "caller-controlled-request"

    event = app.state.retail_store.events()[0]
    assert event["request_id"] == trusted_request_id
    assert event["actor_id"] == alice_session["user"]["id"]
    assert event["session_id"] == alice_session["session_id"]
    assert event["protocol"] == "TCP"
    assert event["destination_port"] == 8080

    flow = NormalizedFlow(
        event_id="flow-checkout-1",
        observed_at=event["occurred_at"] + 0.1,
        source=WorkloadIdentity("retailco", "workload-frontend", "frontend"),
        destination=WorkloadIdentity(
            "retailco", "workload-checkout", "checkoutservice"
        ),
        identity_status="resolved",
        verdict="forwarded",
        drop_reason=None,
        protocol="TCP",
        destination_port=8080,
        node_name="lab-node",
    )
    assert app.state.store.ingest_normalized_flows([flow]) == 1

    login(owner, "owner@example.com", owner_password)
    summary = owner.get("/api/retail/admin/security/summary")
    assert summary.status_code == 200, summary.text
    checkout_evidence = next(
        item for item in summary.json()["applicationEvents"] if item["action"] == "order.checkout"
    )
    assert checkout_evidence["correlation"]["status"] == "exact"
    assert checkout_evidence["correlation"]["flow_event_id"] == "flow-checkout-1"
    assert checkout_evidence["correlation"]["source_name"] == "frontend"

    finding = SimpleNamespace(
        id="checkout-correlation",
        source_id="workload-frontend",
        source_name="frontend",
        source_tenant="retailco",
        destination_id="workload-checkout",
        model_version="test-model",
        window_start=event["occurred_at"] - 1,
        window_end=event["occurred_at"] + 1,
        predicted_probability=0.1,
        anomaly_score=0.9,
        threshold=0.5,
        supporting_facts={"policy_denied": True},
        event_ids=["flow-checkout-1"],
        created_at=event["occurred_at"] + 1,
        accumulated_risk=0.9,
        baseline_score=0.2,
        response="containment-recommended",
    )
    assert app.state.store.record_detection_finding(
        finding,
        [{"id": "flow-checkout-1", "sourceId": "workload-frontend"}],
    )
    incident = next(
        item
        for item in app.state.store.get_incidents()
        if item["id"] == "incident-checkout-correlation"
    )
    assert incident["evidence"][0]["applicationEventRefs"] == [event["id"]]

    app.state.store.create_incident({
        "id": "incident-outside-store",
        "sourceId": "outside-source",
        "sourceName": "outside-source",
        "tenantId": "another-tenant",
        "status": "alert",
        "reason": "Out of scope",
        "createdAt": event["occurred_at"],
        "evidence": [{
            "id": "outside-flow", "at": event["occurred_at"],
            "sourceId": "outside-source", "destinationId": "outside-target",
            "sourceName": "outside-source", "destinationName": "outside-target",
            "sourceTenant": "another-tenant", "destinationTenant": "another-tenant",
            "port": 8080, "decision": "denied", "reason": "default-deny",
        }],
        "trace": [],
    })

    second = NormalizedFlow(
        **{
            **flow.__dict__,
            "event_id": "flow-checkout-2",
            "observed_at": event["occurred_at"] + 0.2,
        }
    )
    assert app.state.store.ingest_normalized_flows([second]) == 1
    summary = owner.get("/api/retail/admin/security/summary").json()
    checkout_evidence = next(
        item for item in summary["applicationEvents"] if item["action"] == "order.checkout"
    )
    assert checkout_evidence["correlation"]["status"] == "inconclusive"
    assert checkout_evidence["correlation"]["flow_event_id"] is None
    assert "timing alone" in checkout_evidence["correlation"]["reason"]
    assert [item["id"] for item in summary["incidents"]] == [
        "incident-checkout-correlation"
    ]

    with app.state.store.connect() as database:
        database.execute(
            "INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
            ("retailco", "RetailCo", "", event["occurred_at"]),
        )
        database.execute(
            """INSERT INTO workloads
               (id,tenant_id,name,template,desired,observed,created)
               VALUES(?,?,?,?,?,?,?)""",
            (
                "workload-frontend", "retailco", "frontend", "web",
                "running", "running", event["occurred_at"],
            ),
        )
    unavailable = owner.post(
        "/api/retail/admin/security/incidents/incident-checkout-correlation/quarantine",
        json={},
    )
    assert unavailable.status_code == 503
    assert "not configured" in unavailable.json()["detail"].lower()
    incident = next(
        item for item in app.state.store.get_incidents()
        if item["id"] == "incident-checkout-correlation"
    )
    assert incident["status"] == "alert"


def test_security_summary_requires_owner_role(tmp_path):
    app, _ = make_lab(tmp_path)
    alice = client(app)
    password = secrets.token_urlsafe(24)
    register_alice(alice, password)
    login(alice, "alice@example.com", password)
    assert alice.get("/api/retail/admin/security/summary").status_code == 403


def test_existing_retail_database_migrates_application_event_fields(tmp_path):
    path = tmp_path / "retail.sqlite"
    with sqlite3.connect(path) as database:
        database.execute(
            """CREATE TABLE application_events(
               id TEXT PRIMARY KEY, occurred_at REAL NOT NULL, request_id TEXT NOT NULL,
               tenant_id TEXT NOT NULL, actor_id TEXT, session_id TEXT,
               source_workload TEXT NOT NULL, destination_workload TEXT NOT NULL,
               action TEXT NOT NULL, route_template TEXT NOT NULL, result TEXT NOT NULL)"""
        )
    store = RetailStore(path)
    with store.connect() as database:
        columns = {
            row["name"] for row in database.execute("PRAGMA table_info(application_events)")
        }
        versions = {
            row["version"] for row in database.execute("SELECT version FROM retail_schema_migrations")
        }
    assert {"protocol", "destination_port"} <= columns
    assert versions == {1, 2}


def test_lab_accounts_allow_short_passwords_only_through_seeding(tmp_path):
    app, _ = make_lab(tmp_path)
    store = app.state.retail_store
    api = client(app)
    rejected = api.post("/api/retail/auth/register", json={"email": "short@example.com", "password": "shortpass", "display_name": "Short Pass"})
    assert rejected.status_code == 422
    user, created = store.upsert_lab_account("lab-owner@example.com", "labpass1", "Lab Owner", role="owner")
    assert created and user["role"] == "owner"
    _, created_again = store.upsert_lab_account("lab-owner@example.com", "labpass2", "Lab Owner", role="owner")
    assert not created_again
    assert api.post("/api/retail/auth/login", json={"email": "lab-owner@example.com", "password": "labpass1"}).status_code == 401
    assert api.post("/api/retail/auth/login", json={"email": "lab-owner@example.com", "password": "labpass2"}).status_code == 200
