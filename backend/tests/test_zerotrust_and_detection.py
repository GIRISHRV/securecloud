import secrets
import pytest
from fastapi.testclient import TestClient
from backend.api import Settings, create_app


@pytest.fixture
def zerotrust_lab(tmp_path):
    settings = Settings(tmp_path / "test.sqlite", origin="http://testserver", secure_cookie=False)
    app = create_app(settings)
    admin_pw = secrets.token_urlsafe(24)
    admin_id = app.state.store.create_user("administrator", admin_pw, administrator=True)

    c = TestClient(app)
    c.headers["Origin"] = settings.origin
    res = c.post("/api/auth/login", json={"username": "administrator", "password": admin_pw})
    assert res.status_code == 200
    c.headers["X-CSRF-Token"] = res.json()["csrf"]

    # Seed demo data (College and Hospital with 3 workloads each)
    app.state.store.seed_demo_data(admin_id)
    return app, c


def test_zero_trust_policy_enforcement_and_traffic_simulation(zerotrust_lab):
    app, client = zerotrust_lab

    # 1. Approved path: college-web -> college-api on port 8080
    r1 = client.post("/api/traffic/simulate", json={
        "source_id": "college-web",
        "destination_id": "college-api",
        "port": 8080
    })
    assert r1.status_code == 200
    assert r1.json()["decision"] == "allowed"
    assert r1.json()["reason"] == "approved-intent"

    # 2. Denied path: cross-tenant college-web -> hospital-api on port 8080
    r2 = client.post("/api/traffic/simulate", json={
        "source_id": "college-web",
        "destination_id": "hospital-api",
        "port": 8080
    })
    assert r2.status_code == 200
    assert r2.json()["decision"] == "denied"
    assert r2.json()["reason"] == "cross-tenant"

    # 3. Denied path: port mismatch within tenant college-web -> college-api on port 9999
    r3 = client.post("/api/traffic/simulate", json={
        "source_id": "college-web",
        "destination_id": "college-api",
        "port": 9999
    })
    assert r3.status_code == 200
    assert r3.json()["decision"] == "denied"
    assert r3.json()["reason"] == "default-deny"


def test_anomaly_detection_burst_triggers_incident_and_quarantine_lifecycle(zerotrust_lab):
    app, client = zerotrust_lab

    # Send 3 cross-tenant attempts to simulate suspicious lateral movement
    for _ in range(3):
        client.post("/api/traffic/simulate", json={
            "source_id": "college-web",
            "destination_id": "hospital-api",
            "port": 8080
        })

    # Verify incident was created
    incidents = client.get("/api/incidents").json()
    assert len(incidents) >= 1
    inc = incidents[0]
    assert inc["sourceId"] == "college-web"
    assert inc["status"] == "alert"
    assert len(inc["evidence"]) >= 3

    # Quarantine workload
    q_res = client.post(f"/api/incidents/{inc['id']}/quarantine", json={})
    assert q_res.status_code == 200
    assert q_res.json()["status"] == "quarantined"

    # Verify previously approved traffic is now DENIED due to quarantine
    r_quarantined = client.post("/api/traffic/simulate", json={
        "source_id": "college-web",
        "destination_id": "college-api",
        "port": 8080
    })
    assert r_quarantined.status_code == 200
    assert r_quarantined.json()["decision"] == "denied"
    assert r_quarantined.json()["reason"] == "quarantine"

    # Operator reviews
    rev_res = client.post(f"/api/incidents/{inc['id']}/review", json={})
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "review"

    # Restore workload
    res_res = client.post(f"/api/incidents/{inc['id']}/restore", json={})
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "restored"

    # Verify approved traffic is allowed again
    r_restored = client.post("/api/traffic/simulate", json={
        "source_id": "college-web",
        "destination_id": "college-api",
        "port": 8080
    })
    assert r_restored.status_code == 200
    assert r_restored.json()["decision"] == "allowed"
    assert r_restored.json()["reason"] == "approved-intent"
