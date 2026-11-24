import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import Settings, create_app


@pytest.fixture
def lab(tmp_path):
    settings = Settings(tmp_path / "test.sqlite", origin="http://testserver", secure_cookie=False)
    app = create_app(settings)
    users = {}
    for name in ("administrator", "alice", "bob", "viewer"):
        password = secrets.token_urlsafe(24)
        users[name] = (app.state.store.create_user(name, password, name == "administrator"), password)

    def client(name):
        c = TestClient(app)
        c.headers["Origin"] = settings.origin
        result = c.post("/api/auth/login", json={"username": name, "password": users[name][1]})
        assert result.status_code == 200, result.text
        c.headers["X-CSRF-Token"] = result.json()["csrf"]
        return c

    admin = client("administrator")
    tenants = [admin.post("/api/tenants", json={"name": name}).json()["id"] for name in ("College", "Hospital")]
    for name, tenant, role in (("alice", tenants[0], "operator"), ("bob", tenants[1], "operator"), ("viewer", tenants[0], "viewer")):
        assert admin.put(f"/api/tenants/{tenant}/memberships", json={"user_id": users[name][0], "role": role}).status_code == 200
    yield app, client, admin, tenants


def deploy(c, tenant, key="deploy-request-1", name="college-web"):
    return c.post(f"/api/tenants/{tenant}/workloads", json={"name": name, "template": "web"}, headers={"Idempotency-Key": key})


def test_authentication_and_cookie_boundaries(lab):
    app, client, admin, tenants = lab
    anonymous = TestClient(app)
    assert anonymous.get("/api/tenants").status_code == 401
    alice = client("alice")
    assert alice.cookies.get("securecloud_dev")
    with app.state.store.connect() as db:
        assert not db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (alice.cookies.get("securecloud_dev"),)).fetchone()
    response = alice.post("/api/auth/logout", json={})
    assert response.status_code == 200
    assert alice.get("/api/auth/session").status_code == 401


def test_authenticated_catalog_exposes_only_bounded_definitions(lab):
    app, client, admin, tenants = lab
    anonymous = TestClient(app)
    assert anonymous.get("/api/catalog").status_code == 401

    catalog = client("alice").get("/api/catalog")
    assert catalog.status_code == 200
    payload = catalog.json()
    assert [item["id"] for item in payload["templates"]] == [
        "web", "api", "database",
    ]
    assert [item["id"] for item in payload["stacks"]] == [
        "retail-stack", "facilities-vendor-stack", "northstar-shop-stack", "bloom-shop-stack", "platform-stack",
    ]
    retail, vendor = payload["stacks"][:2]
    assert retail["status"] == "validated"
    assert retail["deployment_enabled"] is False
    assert len(retail["services"]) == 12
    assert vendor["status"] == "validated"
    assert vendor["deployment_enabled"] is False
    assert len(vendor["services"]) == 3
    serialized = catalog.text.casefold()
    assert '"image"' not in serialized
    assert '"yaml"' not in serialized


def test_cross_tenant_read_and_write_denied(lab):
    app, client, admin, (college, hospital) = lab
    alice = client("alice")
    assert [row["id"] for row in alice.get("/api/tenants").json()] == [college]
    assert alice.get(f"/api/tenants/{hospital}/workloads").status_code == 404
    assert deploy(alice, hospital).status_code == 404
    assert alice.post("/api/tenants", json={"name": "Bypass"}).status_code == 403
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM workloads").fetchone()[0] == 0


def test_stack_deploy_boundary_is_authorized_allowlisted_and_fail_closed(lab):
    app, client, admin, (college, hospital) = lab
    alice = client("alice")
    request = {"name": "retail-app", "stack": "retail-stack"}
    headers = {"Idempotency-Key": "retail-stack-request-1"}

    assert alice.post(
        f"/api/tenants/{hospital}/stacks", json=request, headers=headers
    ).status_code == 404
    response = alice.post(
        f"/api/tenants/{college}/stacks", json=request, headers=headers
    )
    assert response.status_code == 503
    assert alice.post(
        f"/api/tenants/{college}/stacks",
        json={**request, "image": "attacker/image:latest"},
        headers=headers,
    ).status_code == 422
    assert alice.post(
        f"/api/tenants/{college}/stacks",
        json={"name": "vendor-app", "stack": "facilities-vendor-stack"},
        headers={"Idempotency-Key": "vendor-stack-request-1"},
    ).status_code == 503
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM stack_deployments").fetchone()[0] == 0


def test_state_exposes_only_running_management_app_previews(lab):
    app, client, admin, (college, _) = lab
    with app.state.store.connect() as db:
        db.execute(
            """INSERT INTO workloads
               (id,tenant_id,name,template,desired,observed,created)
               VALUES ('college-web',?,'college-web','web','running','running',1)""",
            (college,),
        )
    state = admin.get("/api/state").json()
    workload = next(item for item in state["workloads"] if item["id"] == "college-web")
    assert workload["previewUrl"] == "http://127.0.0.1:8091/"


def test_telemetry_and_incidents_are_tenant_scoped(lab):
    app, client, admin, (college, hospital) = lab
    now = 1_700_000_000.0
    for index, tenant in enumerate((college, hospital)):
        event = {
            "id": f"event-{index}",
            "at": now + index,
            "sourceId": f"source-{index}",
            "destinationId": f"destination-{index}",
            "sourceName": f"source-{index}",
            "destinationName": f"destination-{index}",
            "sourceTenant": tenant,
            "destinationTenant": tenant,
            "port": 8080,
            "decision": "denied",
            "reason": "default-deny",
        }
        app.state.store.record_traffic(event)
        app.state.store.create_incident({
            "id": f"incident-{index}",
            "sourceId": event["sourceId"],
            "sourceName": event["sourceName"],
            "tenantId": tenant,
            "status": "alert",
            "reason": "Test incident",
            "createdAt": now + index,
            "evidence": [event],
            "trace": [{"at": now + index, "title": "Alert", "detail": "Test"}],
        })

    alice = client("alice")
    assert [event["sourceTenant"] for event in alice.get("/api/traffic").json()] == [college]
    assert [incident["tenantId"] for incident in alice.get("/api/incidents").json()] == [college]
    state = alice.get("/api/state").json()
    assert [tenant["id"] for tenant in state["tenants"]] == [college]
    assert [event["sourceTenant"] for event in state["traffic"]] == [college]
    assert alice.get("/api/incidents/incident-1").status_code == 404
    assert alice.post("/api/incidents/incident-1/quarantine", json={}).status_code == 404


def test_csrf_and_origin_required(lab):
    app, client, admin, (college, _) = lab
    alice = client("alice")
    alice.headers.pop("X-CSRF-Token")
    assert deploy(alice, college).status_code == 403
    alice.headers["Origin"] = "https://attacker.invalid"
    assert deploy(alice, college).status_code == 403
    alice.headers.pop("Origin")
    assert deploy(alice, college).status_code == 403


def test_viewer_cannot_mutate_or_promote_self(lab):
    app, client, admin, (college, _) = lab
    viewer = client("viewer")
    assert viewer.get(f"/api/tenants/{college}/workloads").status_code == 200
    assert deploy(viewer, college).status_code == 403
    uid = viewer.get("/api/auth/session").json()["user"]["id"]
    assert viewer.put(f"/api/tenants/{college}/memberships", json={"user_id": uid, "role": "admin"}).status_code == 403


def test_membership_change_applies_to_existing_session(lab):
    app, client, admin, (college, _) = lab
    alice = client("alice")
    uid = alice.get("/api/auth/session").json()["user"]["id"]
    admin.put(f"/api/tenants/{college}/memberships", json={"user_id": uid, "role": "viewer"})
    assert deploy(alice, college).status_code == 403


def test_idempotency_and_pending_state(lab):
    app, client, admin, (college, _) = lab
    alice = client("alice")
    first = deploy(alice, college)
    assert first.status_code == 202
    assert first.json()["status"] == "queued"
    assert deploy(alice, college).json()["id"] == first.json()["id"]
    assert deploy(alice, college, name="changed-name").status_code == 409
    workloads = alice.get(f"/api/tenants/{college}/workloads").json()
    assert len(workloads) == 1 and workloads[0]["observed"] == "pending"
    assert TestClient(create_app(app.state.settings)).get("/api/health").json()["infrastructure"] == {
        "connected": False,
        "provider": "disabled",
    }


def test_exact_name_version_serialization_and_quarantine(lab):
    app, client, admin, (college, _) = lab
    alice = client("alice")
    op = deploy(alice, college).json()
    target = f"/api/tenants/{college}/workloads/{op['workload_id']}"
    headers = {"Idempotency-Key": "stop-request-1"}
    assert alice.post(target + "/stop", json={"confirmation": "college-web", "expected_version": 1}, headers=headers).status_code == 409
    # Test fixture represents a reconciler completing provisioning, not real K8s evidence.
    with app.state.store.connect() as db:
        db.execute("UPDATE operations SET status='succeeded' WHERE id=?", (op["id"],))
        db.execute("UPDATE workloads SET observed='running',quarantined=1 WHERE id=?", (op["workload_id"],))
    assert alice.post(target + "/stop", json={"confirmation": "wrong-name", "expected_version": 1}, headers=headers).status_code == 409
    assert alice.post(target + "/stop", json={"confirmation": "college-web", "expected_version": 99}, headers=headers).status_code == 409
    assert alice.post(target + "/delete", json={"confirmation": "college-web", "expected_version": 1}, headers=headers).status_code == 409
    result = alice.post(target + "/stop", json={"confirmation": "college-web", "expected_version": 1}, headers=headers)
    assert result.status_code == 202
    assert alice.post(target + "/stop", json={"confirmation": "college-web", "expected_version": 1}, headers=headers).json()["id"] == result.json()["id"]
    row = alice.get(f"/api/tenants/{college}/workloads").json()[0]
    assert row["quarantined"] == 1 and row["desired"] == "stopped" and row["observed"] == "running"


def test_two_concurrent_deploys_same_key_create_one_operation(lab):
    app, client, admin, (college, _) = lab
    alice = client("alice")
    def run(_):
        with TestClient(app) as c:
            c.cookies.update(alice.cookies)
            c.headers.update(alice.headers)
            return deploy(c, college)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(run, range(2)))
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json()["id"] == responses[1].json()["id"]


def test_input_allowlist_limits_and_no_password_echo(lab):
    app, client, admin, (college, _) = lab
    alice = client("alice")
    assert alice.post(f"/api/tenants/{college}/workloads", json={"name": "valid-name", "template": "web", "image": "arbitrary"}).status_code == 422
    assert admin.post("/api/tenants", json={"name": "Third tenant"}).status_code == 409
    secret = secrets.token_urlsafe(32)
    response = alice.post("/api/auth/login", json={"username": "alice", "password": secret, "extra": secret})
    assert response.status_code == 422 and secret not in response.text
    assert alice.post("/api/tenants", content=b"x" * 20000, headers={"Content-Type": "application/json"}).status_code == 413


def test_disabled_and_expired_sessions_rejected(lab):
    app, client, admin, tenants = lab
    alice = client("alice")
    uid = alice.get("/api/auth/session").json()["user"]["id"]
    with app.state.store.connect() as db:
        db.execute("UPDATE users SET disabled=1 WHERE id=?", (uid,))
    assert alice.get("/api/tenants").status_code == 401
    bob = client("bob")
    with app.state.store.connect() as db:
        db.execute("UPDATE sessions SET expires=0")
    assert bob.get("/api/tenants").status_code == 401


def test_login_throttle_persists_and_audit_contains_no_secrets(lab):
    app, client, admin, tenants = lab
    c = TestClient(app, headers={"Origin": "http://testserver"})
    secret = secrets.token_urlsafe(24)
    for _ in range(8):
        assert c.post("/api/auth/login", json={"username": "nobody", "password": secret}).status_code == 401
    restarted = TestClient(create_app(app.state.settings), headers={"Origin": "http://testserver"})
    assert restarted.post("/api/auth/login", json={"username": "nobody", "password": secret}).status_code == 429
    with app.state.store.connect() as db:
        assert secret not in str([dict(r) for r in db.execute("SELECT * FROM audit")])


def test_secure_cookie_default_and_host_validation(tmp_path):
    with pytest.raises(ValueError, match="Infrastructure"):
        Settings(tmp_path / "invalid.sqlite", infrastructure="docker")
    app = create_app(Settings(tmp_path / "secure.sqlite", origin="https://testserver"))
    password = secrets.token_urlsafe(24)
    app.state.store.create_user("admin", password, True)
    c = TestClient(app, base_url="https://testserver", headers={"Origin": "https://testserver"})
    response = c.post("/api/auth/login", json={"username": "admin", "password": password})
    cookie = response.headers["set-cookie"].lower()
    assert "__host-securecloud=" in cookie and "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/tenants", headers={"Host": "attacker.invalid"}).status_code == 400
