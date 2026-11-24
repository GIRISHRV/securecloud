"""Live-lab harness: verdicts must come from Hubble records, never from the probe's own view."""
import json
import time
from types import SimpleNamespace

import pytest

from backend.lab import LabService, LabUnavailable
from backend.lab.service import _last_json
from backend.store import Store
from backend.telemetry.schema import NormalizedFlow, WorkloadIdentity


def seed(store: Store):
    now = time.time()
    with store.connect() as db:
        for tenant, name in (("t-north", "Northstar"), ("t-bloom", "Bloom"), ("t-platform", "Platform")):
            db.execute("INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)", (tenant, name, "", now))
        db.execute("INSERT INTO stack_deployments VALUES('s-north','t-north','northstar','northstar-shop-stack','running','running',1,?)", (now,))
        db.execute("INSERT INTO stack_deployments VALUES('s-bloom','t-bloom','bloom','bloom-shop-stack','running','running',1,?)", (now,))
        db.execute("INSERT INTO stack_deployments VALUES('s-platform','t-platform','platform','platform-stack','running','running',1,?)", (now,))
        rows = [
            ("w-plugin", "t-north", "shipfast-plugin", "api", "s-north"),
            ("w-napi", "t-north", "northstar-api", "api", "s-north"),
            ("w-ndb", "t-north", "northstar-database", "database", "s-north"),
            ("w-bapi", "t-bloom", "bloom-api", "api", "s-bloom"),
            ("w-bdb", "t-bloom", "bloom-database", "database", "s-bloom"),
            ("w-bweb", "t-bloom", "bloom-web", "web", "s-bloom"),
            ("w-pay", "t-platform", "payments", "api", "s-platform"),
            ("w-email", "t-platform", "email", "api", "s-platform"),
        ]
        for wid, tenant, name, template, stack in rows:
            db.execute(
                "INSERT INTO workloads(id,tenant_id,name,template,desired,observed,quarantined,version,created,stack_deployment_id)"
                " VALUES(?,?,?,?,'running','running',0,1,?,?)",
                (wid, tenant, name, template, now, stack),
            )


class FakeCluster:
    """Answers exec with a LABRESULT line and, optionally, emits Hubble flows."""

    def __init__(self, store, verdict=None):
        self.store, self.verdict, self.commands = store, verdict, []

    def health(self):
        return {"provider": "fake", "version": "v-test"}

    def workload_pod_ip(self, namespace, workload_id):
        return f"{workload_id}.pod-ip"

    def exec_in_workload(self, namespace, workload_id, argv, timeout=90.0):
        self.commands.append(argv)
        spec = json.loads(argv[-1])
        results = [{"i": t["i"], "result": "timeout", "ms": 1500} for t in spec for _ in range(t["count"])]
        if self.verdict:
            ident = {w.workload_id: w for w in self.store.workload_identities()}
            targets = {"bloom-api": "w-bapi", "bloom-database": "w-bdb", "bloom-web": "w-bweb", "northstar-database": "w-ndb", "payments": "w-pay", "email": "w-email"}
            flows = []
            for t in spec:
                name = t["host"].split(".")[0]
                flows.append(NormalizedFlow(
                    event_id=f"flow-{t['i']}", observed_at=time.time(), source=ident["w-plugin"],
                    destination=ident[targets.get(name, name)], identity_status="resolved", verdict=self.verdict,
                    drop_reason="POLICY_DENIED" if self.verdict == "dropped" else None, protocol="TCP",
                    destination_port=t["port"], node_name="lab",
                ))
            self.store.ingest_normalized_flows(flows)
        return "noise line\nLABRESULT " + json.dumps(results)


def wait(lab, run_id):
    for _ in range(100):
        run = lab.run(run_id)
        if run["status"] in ("completed", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("lab run did not finish")


def make(tmp_path, verdict):
    store = Store(tmp_path / "core.sqlite")
    seed(store)
    cluster = FakeCluster(store, verdict)
    telemetry = {"enabled": True, "last_poll": time.time(), "accepted": 1, "detector": "test"}
    return LabService(store, cluster, telemetry, observe_seconds=0.3), cluster


def test_observed_drops_become_blocked_verdicts(tmp_path):
    lab, cluster = make(tmp_path, "dropped")
    run = wait(lab, lab.start("plugin-lateral-movement", "owner@example.test")["id"])
    assert run["status"] == "completed"
    assert all(step["state"] == "matched" and step["verdict"]["observed"] == "blocked" for step in run["steps"])
    assert run["result"]["blocked_as_expected"] == 6
    kinds = [line["kind"] for line in run["log"]]
    assert "cmd" in kinds and kinds.count("drop") == 6 and kinds.count("out") == 12
    # Targets are server-resolved lab service names, never caller input.
    assert all(t["host"].endswith((".svc.cluster.local", ".pod-ip")) for t in json.loads(cluster.commands[0][-1]))


def test_probe_timeouts_without_hubble_flows_stay_inconclusive(tmp_path):
    lab, _ = make(tmp_path, None)
    run = wait(lab, lab.start("plugin-lateral-movement", "owner@example.test")["id"])
    assert {step["state"] for step in run["steps"]} == {"inconclusive"}
    assert run["result"]["blocked_as_expected"] == 0
    assert all(step["client"]["failed"] == 2 for step in run["steps"])


def test_unknown_scenarios_and_offline_labs_are_rejected(tmp_path):
    lab, _ = make(tmp_path, None)
    with pytest.raises(KeyError):
        lab.start("rm -rf /", "owner@example.test")
    lab.telemetry["enabled"] = False
    with pytest.raises(LabUnavailable):
        lab.start("plugin-lateral-movement", "owner@example.test")
    offline = LabService(lab.store, None, {"enabled": True})
    assert offline.status()["ready"] is False


def test_result_parser_ignores_unprefixed_output():
    assert _last_json('{"looks": "like json"}') is None
    assert _last_json("x\nLABRESULT [1, 2]") == [1, 2]


def test_findings_for_an_open_incident_attach_instead_of_duplicating(tmp_path):
    store = Store(tmp_path / "core.sqlite")
    seed(store)

    def finding(fid, dest):
        return SimpleNamespace(
            id=fid, model_version="m", window_start=0.0, window_end=30.0, source_id="w-vapi", source_name="vendor-api",
            source_tenant="t-vendor", destination_id=dest, predicted_probability=0.01, anomaly_score=0.99, threshold=0.5,
            supporting_facts={"policy_denied": True}, event_ids=(f"e-{fid}",), created_at=time.time(),
            accumulated_risk=0.9, baseline_score=0.2, response="containment-recommended",
        )

    evidence = lambda fid, name: [{"id": f"e-{fid}", "destinationName": name}]
    assert store.record_detection_finding(finding("a", "w-pay"), evidence("a", "paymentservice")) is True
    assert store.record_detection_finding(finding("b", "w-cart"), evidence("b", "cartservice")) is False
    with store.connect() as db:
        incidents = db.execute("SELECT evidence_json,trace_json FROM incidents").fetchall()
    assert len(incidents) == 1
    assert len(json.loads(incidents[0]["evidence_json"])) == 2
    assert "cartservice" in json.loads(incidents[0]["trace_json"])[-1]["detail"]


def test_catalog_dependencies_are_approved_edges(tmp_path):
    store = Store(tmp_path / "core.sqlite")
    seed(store)
    edges = store.approved_edges()
    # The plugin may call the shop's order API (declared intent) and nothing else.
    assert ("w-plugin", "w-napi") in edges
    assert ("w-napi", "w-ndb") in edges and ("w-bweb", "w-bapi") in edges
    assert ("w-plugin", "w-ndb") not in edges
    assert ("w-plugin", "w-bapi") not in edges
    # Shop order APIs may use the shared platform; plugins may not.
    assert ("w-napi", "w-pay") in edges and ("w-bapi", "w-email") in edges
    assert ("w-plugin", "w-pay") not in edges


def test_forwarded_reply_legs_are_not_ingested(tmp_path):
    from backend.telemetry import HubbleJsonFileCollector, IdentityIndex

    path = tmp_path / "hubble.jsonl"
    record = lambda uuid, reply, verdict: json.dumps({"flow": {
        "uuid": uuid, "time": "2026-11-24T07:00:00Z", "verdict": verdict, "is_reply": reply,
        "source": {"namespace": "a", "labels": []}, "destination": {"namespace": "b", "labels": []},
        "l4": {"TCP": {"destination_port": 80}}}})
    path.write_text("\n".join([record("req", False, "FORWARDED"), record("rep", True, "FORWARDED"), record("drop", True, "DROPPED")]) + "\n")
    batch = HubbleJsonFileCollector(path, lambda: IdentityIndex([])).poll()
    assert {flow.event_id for flow in batch.flows} == {"req", "drop"}


def test_only_alerts_can_be_dismissed_and_dismissal_is_audited(tmp_path):
    store = Store(tmp_path / "core.sqlite")
    seed(store)
    finding = SimpleNamespace(
        id="f1", model_version="m", window_start=0.0, window_end=30.0, source_id="w-vapi", source_name="vendor-api",
        source_tenant="t-vendor", destination_id="w-pay", predicted_probability=0.01, anomaly_score=0.99, threshold=0.5,
        supporting_facts={}, event_ids=("e1",), created_at=time.time(), accumulated_risk=0.9, baseline_score=0.2, response="observe",
    )
    store.record_detection_finding(finding, [{"id": "e1", "destinationName": "paymentservice"}])
    entry = {"at": time.time(), "title": "Alert dismissed", "detail": "test"}
    store.update_incident_status("incident-f1", "closed", entry, actor="owner-1")
    with pytest.raises(ValueError):
        store.update_incident_status("incident-f1", "closed", entry, actor="owner-1")
    with store.connect() as db:
        assert db.execute("SELECT status FROM incidents").fetchone()[0] == "closed"
        assert db.execute("SELECT COUNT(*) FROM audit WHERE action='incident.dismissed'").fetchone()[0] == 1


def test_protection_toggle_reaches_every_lab_namespace(tmp_path):
    lab, cluster = make(tmp_path, None)
    calls = []
    cluster.set_protection = lambda enabled, namespaces: calls.append((enabled, sorted(namespaces)))
    assert lab.set_protection(False)["protection"] is False
    assert lab.set_protection(True)["protection"] is True
    assert [enabled for enabled, _ in calls] == [False, True]
    assert len(calls[0][1]) == 3  # Northstar, Bloom and the platform zone


def test_reset_starts_a_clean_demo_session(tmp_path):
    lab, _ = make(tmp_path, "dropped")
    wait(lab, lab.start("plugin-lateral-movement", "owner@example.test")["id"])
    assert len(lab.runs()) == 1
    lab.reset()
    assert lab.runs() == []


def test_exfiltration_targets_only_a_reserved_test_address(tmp_path):
    lab, cluster = make(tmp_path, None)
    seed_extra = lab.store
    with seed_extra.connect() as db:  # the order API is the exfiltration source
        db.execute("UPDATE workloads SET name='northstar-api' WHERE id='w-napi'")
    run = wait(lab, lab.start("data-exfiltration", "owner@example.test")["id"])
    hosts = {t["host"] for t in json.loads(cluster.commands[0][-1])}
    assert hosts == {"203.0.113.10"}  # RFC 5737 TEST-NET-3: never routed
    assert all(step["target_id"] is None and step["state"] == "inconclusive" for step in run["steps"])


def test_restart_scenario_replaces_the_pod_before_probing(tmp_path):
    lab, cluster = make(tmp_path, None)
    calls = []
    cluster.restart_workload = lambda namespace, workload_id, name: calls.append(name) or ("pod-old", "pod-new", 4.2)
    run = wait(lab, lab.start("quarantine-restart", "owner@example.test")["id"])
    assert calls == ["shipfast-plugin"]
    assert any("pod-old replaced by pod-new" in line["text"] for line in run["log"])
