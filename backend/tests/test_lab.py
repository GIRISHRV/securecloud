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
        for tenant, name in (("t-vendor", "FacilitiesVendor"), ("t-retail", "RetailCo")):
            db.execute("INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)", (tenant, name, "", now))
        db.execute("INSERT INTO stack_deployments VALUES('s-vendor','t-vendor','vendor','facilities-vendor-stack','running','running',1,?)", (now,))
        db.execute("INSERT INTO stack_deployments VALUES('s-retail','t-retail','retail','retail-stack','running','running',1,?)", (now,))
        rows = [
            ("w-vapi", "t-vendor", "vendor-api", "api", "s-vendor"),
            ("w-vdb", "t-vendor", "vendor-database", "database", "s-vendor"),
            ("w-pay", "t-retail", "paymentservice", "api", "s-retail"),
            ("w-cart", "t-retail", "cartservice", "api", "s-retail"),
            ("w-checkout", "t-retail", "checkoutservice", "api", "s-retail"),
            ("w-redis", "t-retail", "redis-cart", "database", "s-retail"),
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
        return "10.0.0.9"

    def exec_in_workload(self, namespace, workload_id, argv, timeout=90.0):
        self.commands.append(argv)
        spec = json.loads(argv[-1])
        results = [{"i": t["i"], "result": "timeout", "ms": 1500} for t in spec for _ in range(t["count"])]
        if self.verdict:
            ident = {w.workload_id: w for w in self.store.workload_identities()}
            targets = {"paymentservice": "w-pay", "cartservice": "w-cart", "checkoutservice": "w-checkout", "redis-cart": "w-redis"}
            flows = []
            for t in spec:
                name = t["host"].split(".")[0]
                flows.append(NormalizedFlow(
                    event_id=f"flow-{t['i']}", observed_at=time.time(), source=ident["w-vapi"],
                    destination=ident[targets[name]], identity_status="resolved", verdict=self.verdict,
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
    run = wait(lab, lab.start("vendor-lateral-movement", "owner@example.test")["id"])
    assert run["status"] == "completed"
    assert all(step["state"] == "matched" and step["verdict"]["observed"] == "blocked" for step in run["steps"])
    assert run["result"]["blocked_as_expected"] == 4
    kinds = [line["kind"] for line in run["log"]]
    assert "cmd" in kinds and kinds.count("drop") == 4 and kinds.count("out") == 12
    # Targets are server-resolved lab service names, never caller input.
    assert all(t["host"].endswith(".svc.cluster.local") for t in json.loads(cluster.commands[0][-1]))


def test_probe_timeouts_without_hubble_flows_stay_inconclusive(tmp_path):
    lab, _ = make(tmp_path, None)
    run = wait(lab, lab.start("vendor-lateral-movement", "owner@example.test")["id"])
    assert {step["state"] for step in run["steps"]} == {"inconclusive"}
    assert run["result"]["blocked_as_expected"] == 0
    assert all(step["client"]["failed"] == 3 for step in run["steps"])


def test_unknown_scenarios_and_offline_labs_are_rejected(tmp_path):
    lab, _ = make(tmp_path, None)
    with pytest.raises(KeyError):
        lab.start("rm -rf /", "owner@example.test")
    lab.telemetry["enabled"] = False
    with pytest.raises(LabUnavailable):
        lab.start("vendor-lateral-movement", "owner@example.test")
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
    # checkoutservice → paymentservice is a declared retail-stack dependency (api → api).
    assert ("w-checkout", "w-pay") in edges
    assert ("w-vapi", "w-vdb") in edges
    assert ("w-vapi", "w-pay") not in edges


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
