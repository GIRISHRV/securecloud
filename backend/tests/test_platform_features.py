"""Security modes, pause/resume, team access, policy advisor, evidence pack, scorecard, MITRE tags."""
import json
import time
import uuid

from fastapi.testclient import TestClient

from backend.lab.scenarios import BY_ID
from backend.tests.test_shops import make_mall, provider_client, request, signed_in


class ScalingCluster:
    def __init__(self):
        self.calls = []

    def scale_shop(self, tenant_id, replicas):
        self.calls.append(replicas)
        return "pending" if len(self.calls) % 2 else "done"  # one loop to settle, like Kubernetes


def test_new_shops_learn_then_monitor_and_the_provider_can_set_protect(tmp_path):
    app, password, users = make_mall(tmp_path)
    shops = app.state.shops
    shop = shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    assert shops.mode(shop) == "learn" and shops.mode_for_tenant(shop["tenant_id"]) == "learn"
    with shops.connect() as db:  # pretend the warm-up has passed
        db.execute("UPDATE shops SET created_at=? WHERE slug='terra-pots'", (time.time() - 3600,))
    assert shops.mode(shops.get("terra-pots")) == "monitor"
    provider = provider_client(app, password)
    assert provider.post("/api/provider/admin/shops/terra-pots/mode", json={"mode": "protect"}).json()["mode"] == "protect"
    assert shops.mode_for_tenant(shop["tenant_id"]) == "protect"
    assert provider.post("/api/provider/admin/shops/terra-pots/mode", json={"mode": "chaos"}).status_code == 422
    assert shops.mode_for_tenant("some-platform-tenant") == "monitor"  # never auto-act on non-shops


def test_owner_pauses_and_resumes_only_after_the_cluster_confirms(tmp_path):
    app, password, users = make_mall(tmp_path)
    app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    maya, ravi = signed_in(app, "maya@example.com", password), signed_in(app, "ravi@example.com", password)
    assert ravi.post("/api/mall/shops/terra-pots/pause", json={"confirm": "terra-pots"}).status_code == 404
    assert maya.post("/api/mall/shops/terra-pots/pause", json={"confirm": "wrong"}).status_code == 422
    assert maya.post("/api/mall/shops/terra-pots/pause", json={"confirm": "terra-pots"}).json()["state"] == "pausing"
    assert TestClient(app).get("/api/shops/terra-pots/products").status_code == 503
    cluster = ScalingCluster()
    app.state.shops.reconcile_lifecycle(cluster)
    assert app.state.shops.get("terra-pots")["status"] == "pausing"
    app.state.shops.reconcile_lifecycle(cluster)
    assert app.state.shops.get("terra-pots")["status"] == "paused" and cluster.calls == [0, 0]
    assert maya.post("/api/mall/shops/terra-pots/resume", json={"confirm": "terra-pots"}).status_code == 202
    app.state.shops.reconcile_lifecycle(cluster)
    app.state.shops.reconcile_lifecycle(cluster)
    assert app.state.shops.get("terra-pots")["status"] == "active" and cluster.calls[-1] == 1
    assert TestClient(app).get("/api/shops/terra-pots/products").status_code == 200


def test_owner_invites_staff_who_can_run_the_shop_but_not_the_team(tmp_path):
    app, password, users = make_mall(tmp_path)
    app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    maya, ravi = signed_in(app, "maya@example.com", password), signed_in(app, "ravi@example.com", password)
    assert ravi.get("/api/shops/terra-pots/admin/orders").status_code == 403
    assert maya.post("/api/mall/shops/terra-pots/team", json={"email": "nobody@example.com"}).status_code == 422
    assert maya.post("/api/mall/shops/terra-pots/team", json={"email": "ravi@example.com"}).status_code == 201
    assert ravi.get("/api/shops/terra-pots/admin/orders").status_code == 200       # staff manage the shop
    assert ravi.get("/api/mall/shops/terra-pots/team").json()["owner_is_you"] is False
    assert ravi.post("/api/mall/shops/terra-pots/team", json={"email": "maya@example.com"}).status_code == 404  # not the team
    assert maya.delete(f"/api/mall/shops/terra-pots/team/{users['ravi@example.com']['id']}", headers={"Content-Type": "application/json"}).status_code == 204
    assert ravi.get("/api/shops/terra-pots/admin/orders").status_code == 403


def _flow(db, source, destination, verdict, port=8080, at=None):
    db.execute("""INSERT INTO normalized_flows(event_id,observed_at,source_tenant,source_workload,source_name,destination_tenant,
                  destination_workload,destination_name,identity_status,verdict,drop_reason,protocol,destination_port,node_name)
                  VALUES(?,?,?,?,?,?,?,?,'resolved',?,?,'TCP',?,'lab')""",
               (uuid.uuid4().hex, at or time.time(), source[0], source[1], source[2], destination[0] if destination else None,
                destination[1] if destination else None, destination[2] if destination else None, verdict,
                None if verdict == "forwarded" else "POLICY_DENIED", port))


def test_policy_advisor_suggests_review_but_keeps_cross_tenant_blocks(tmp_path):
    app, password, _ = make_mall(tmp_path)
    store = app.state.store
    with store.connect() as db:
        for tenant, name in (("t1", "Alpha"), ("t2", "Beta")):
            db.execute("INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)", (tenant, name, "", 0))
        for wid, tenant, name, template in (("w-web", "t1", "a-web", "web"), ("w-api", "t1", "a-api", "api"),
                                            ("w-db", "t1", "a-database", "database"), ("w-other", "t2", "b-api", "api")):
            db.execute("INSERT INTO workloads(id,tenant_id,name,template,desired,observed,created) VALUES(?,?,?,?,'running','running',0)",
                       (wid, tenant, name, template))
        _flow(db, ("t1", "w-web", "a-web"), ("t1", "w-api", "a-api"), "forwarded")
        _flow(db, ("t1", "w-web", "a-web"), ("t1", "w-db", "a-database"), "dropped", 5432)
        _flow(db, ("t1", "w-api", "a-api"), ("t2", "w-other", "b-api"), "dropped")
    advice = provider_client(app, password).get("/api/provider/admin/policy/advice").json()
    blocked = {(item["source"], item["destination"]): item for item in advice["blocked_paths"]}
    assert blocked[("a-api", "b-api")]["recommendation"] == "keep-blocked"            # crosses a tenant wall
    review = blocked[("a-web", "a-database")]
    assert review["recommendation"] == "review" and "never applies this automatically" in review["draft"]
    assert {(u["source"], u["destination"]) for u in advice["unused_permissions"]} >= {("a-api", "a-database")}


def test_evidence_pack_is_hashed_and_complete(tmp_path):
    app, password, _ = make_mall(tmp_path)
    store = app.state.store
    with store.connect() as db:
        db.execute("INSERT INTO tenants(id,name,description,created) VALUES('t1','Alpha','',0)")
        db.execute("INSERT INTO workloads(id,tenant_id,name,template,desired,observed,created) VALUES('w1','t1','a-api','api','running','running',0)")
    store.create_incident({"id": "incident-x", "sourceId": "w1", "sourceName": "a-api", "tenantId": "t1", "status": "alert",
                           "reason": "test", "createdAt": time.time(), "evidence": [{"id": "e1"}], "trace": []})
    provider = provider_client(app, password)
    response = provider.get("/api/provider/admin/security/incidents/incident-x/evidence")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    bundle = response.json()
    assert bundle["format"] == "securecloud-evidence-v1" and len(bundle["sha256"]) == 64
    assert bundle["incident"]["id"] == "incident-x" and {"findings", "risk_windows", "audit_trail", "live_policies"} <= set(bundle)
    assert provider.get("/api/provider/admin/security/incidents/nope/evidence").status_code == 404


def test_scorecard_computes_only_from_recorded_runs(tmp_path):
    app, password, _ = make_mall(tmp_path)
    store = app.state.store
    from backend.lab.service import SCHEMA
    now = time.time()
    with store.connect() as db:
        db.executescript(SCHEMA)
        for run_id, scenario, result in (
            ("r1", "plugin-lateral-movement", {"blocked_as_expected": 5, "expected_blocks": 6, "inconclusive": 1, "protection": True}),
            ("r0", "plugin-port-scan", {"blocked_as_expected": 0, "expected_blocks": 7, "inconclusive": 0, "protection": False}),
            ("r2", "normal-checkout", {"order_ms": 120, "protection": True}),
            ("r3", "normal-checkout", {"order_ms": 100, "protection": False}),
        ):
            db.execute("INSERT INTO lab_runs(id,scenario_id,status,actor,created_at,started_at,finished_at,source_workload,result_json) VALUES(?,?,?,?,?,?,?,?,?)",
                       (run_id, scenario, "completed", "t", now - 60, now - 60, now - 50, "src-" + run_id, json.dumps(result)))
        db.execute("INSERT INTO risk_observations(model_version,window_start,window_end,source_id,destination_id,anomaly_score,accumulated_risk,baseline_score,threshold,corroborated,response) VALUES('m',?,?,'src-r1','d',0.9,0.9,0.1,0.5,1,'containment-recommended')",
                   (now - 60, now - 40))
    card = provider_client(app, password).get("/api/provider/admin/lab/scorecard").json()
    assert card["prevention_rate"] == 1.0 and card["prevention"]["unverified"] == 1  # unobserved is not counted either way
    assert card["baseline_prevention_rate"] == 0.0                                    # SecureCloud off: nothing stopped
    assert card["detection_rate"] == 1.0 and card["false_positive_rate"] == 0.0
    assert card["time_to_detect_s"] == 20.0 and card["overhead"]["delta_ms"] == 20.0
    assert card["containment_time_s"] is None  # nothing measured, nothing invented


def test_every_attack_scenario_carries_a_mitre_technique():
    attacks = [s for s in BY_ID.values() if s.kind == "attack"]
    assert attacks and all(s.mitre and all(t.startswith("T") for t, _ in s.mitre) for s in attacks)
    assert {"cloud-metadata", "reach-control-plane"} <= set(BY_ID)
