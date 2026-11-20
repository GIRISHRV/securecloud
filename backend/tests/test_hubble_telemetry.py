import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.api import Settings, create_app
from backend.infrastructure.kubernetes import tenant_namespace
from backend.store import Store
from backend.telemetry import (
    HubbleJsonFileCollector,
    HubbleNormalizationError,
    IdentityIndex,
    WorkloadIdentity,
    build_graph_snapshots,
    normalize_hubble_flow,
    normalize_hubble_json_line,
)


COLLEGE_WEB = WorkloadIdentity("college-id", "workload-web", "college-web")
COLLEGE_API = WorkloadIdentity("college-id", "workload-api", "college-api")
HOSPITAL_API = WorkloadIdentity("hospital-id", "hospital-api-id", "hospital-api")


def index():
    return IdentityIndex([COLLEGE_WEB, COLLEGE_API, HOSPITAL_API])


def payload(
    identifier: str,
    at: str,
    *,
    destination=COLLEGE_API,
    verdict="FORWARDED",
    port=8080,
):
    return {
        "time": at,
        "uuid": identifier,
        "verdict": verdict,
        "drop_reason_desc": "POLICY_DENIED" if verdict == "DROPPED" else None,
        "source": {
            "namespace": tenant_namespace(COLLEGE_WEB.tenant_id),
            "pod_name": "college-web-7f89f9d8c4-test",
            "workloads": [{"name": COLLEGE_WEB.workload_name, "kind": "Deployment"}],
        },
        "destination": {
            "namespace": tenant_namespace(destination.tenant_id),
            "pod_name": f"{destination.workload_name}-7f89f9d8c4-test",
            "workloads": [{"name": destination.workload_name, "kind": "Deployment"}],
        },
        "l4": {"TCP": {"source_port": 41000, "destination_port": port}},
        "node_name": "securecloud-node",
    }


def test_normalizes_official_hubble_fields_to_stable_workload_ids():
    flow = normalize_hubble_flow(
        {"flow": payload("flow-1", "2026-11-13T09:00:01.250Z")},
        index(),
    )
    assert flow.source == COLLEGE_WEB
    assert flow.destination == COLLEGE_API
    assert flow.identity_status == "resolved"
    assert flow.verdict == "forwarded"
    assert flow.protocol == "tcp"
    assert flow.destination_port == 8080
    assert flow.cross_tenant is False
    assert flow.policy_denied is False


def test_preserves_unmapped_identity_as_inconclusive():
    raw = payload("unknown-destination", "2026-11-13T09:00:02Z")
    raw["destination"] = {
        "namespace": "external-namespace",
        "pod_name": "unknown-pod",
    }
    flow = normalize_hubble_flow(raw, index())
    assert flow.identity_status == "unmapped"
    assert flow.destination is None
    snapshot = build_graph_snapshots([flow])[0]
    assert snapshot.edges == ()
    assert snapshot.inconclusive_count == 1


def test_builds_deterministic_30_second_graph_snapshots_and_deduplicates():
    allowed = normalize_hubble_flow(
        payload("allowed", "2026-11-13T09:00:01Z"),
        index(),
    )
    denied = normalize_hubble_flow(
        payload(
            "denied",
            "2026-11-13T09:00:20Z",
            verdict="DROPPED",
            port=8443,
        ),
        index(),
    )
    later = normalize_hubble_flow(
        payload(
            "later",
            "2026-11-13T09:00:30Z",
            destination=HOSPITAL_API,
            verdict="DROPPED",
        ),
        index(),
    )

    first = build_graph_snapshots([later, denied, allowed, allowed])
    second = build_graph_snapshots([allowed, later, denied])
    assert first == second
    assert len(first) == 2
    edge = first[0].edges[0]
    assert edge.flow_count == 2
    assert edge.allowed_count == 1
    assert edge.denied_count == 1
    assert edge.destination_ports == (8080, 8443)
    assert first[1].edges[0].cross_tenant is True


def test_rejects_malformed_or_oversized_json_without_guessing():
    with pytest.raises(HubbleNormalizationError, match="valid JSON"):
        normalize_hubble_json_line("{broken", index())
    with pytest.raises(HubbleNormalizationError, match="size limit"):
        normalize_hubble_json_line("{}", index(), max_bytes=1)

    invalid_port = payload("bad-port", "2026-11-13T09:00:01Z", port=70000)
    with pytest.raises(HubbleNormalizationError, match="port"):
        normalize_hubble_json_line(json.dumps(invalid_port), index())


def test_hashes_records_that_do_not_have_a_hubble_uuid():
    raw = payload("temporary", "2026-11-13T09:00:01Z")
    del raw["uuid"]
    one = normalize_hubble_flow(raw, index())
    two = normalize_hubble_flow(raw, index())
    assert one.event_id == two.event_id
    assert one.event_id.startswith("hubble-")


def test_file_collector_waits_for_complete_lines_and_recovers_after_rotation(tmp_path):
    path = tmp_path / "hubble-events.log"
    first = json.dumps(payload("first", "2026-11-13T09:00:01Z"))
    second = json.dumps(payload("second", "2026-11-13T09:00:02Z"))
    split = len(second) - 8
    path.write_text(first + "\n" + second[:split], encoding="utf-8")
    collector = HubbleJsonFileCollector(path, index)

    batch = collector.poll()
    assert [flow.event_id for flow in batch.flows] == ["first"]
    first_offset = batch.next_offset

    with path.open("a", encoding="utf-8") as stream:
        stream.write(second[split:] + "\n")
    batch = collector.poll()
    assert [flow.event_id for flow in batch.flows] == ["second"]
    assert batch.next_offset > first_offset

    path.unlink()
    path.write_text(
        json.dumps(payload("rotated", "2026-11-13T09:00:31Z")) + "\n",
        encoding="utf-8",
    )
    batch = collector.poll()
    assert [flow.event_id for flow in batch.flows] == ["rotated"]


def test_file_collector_counts_rejected_records_without_stopping(tmp_path):
    path = tmp_path / "hubble-events.log"
    valid = json.dumps(payload("valid", "2026-11-13T09:00:01Z"))
    path.write_text("{broken\n" + valid + "\n", encoding="utf-8")
    batch = HubbleJsonFileCollector(path, index).poll()
    assert batch.rejected_count == 1
    assert [flow.event_id for flow in batch.flows] == ["valid"]


def test_normalized_flow_storage_is_deduplicated_and_round_trips(tmp_path):
    store = Store(tmp_path / "telemetry.sqlite")
    flow = normalize_hubble_flow(
        payload("stored", "2026-11-13T09:00:01Z"),
        index(),
    )
    assert store.ingest_normalized_flows([flow, flow]) == 1
    assert store.ingest_normalized_flows([flow]) == 0
    assert store.get_normalized_flows() == [flow]


def test_normalized_flow_query_keeps_the_latest_bounded_window(tmp_path):
    store = Store(tmp_path / "telemetry.sqlite")
    flows = [
        normalize_hubble_flow(
            payload(f"flow-{sequence}", f"2026-11-13T09:00:0{sequence}Z"),
            index(),
        )
        for sequence in (1, 2, 3)
    ]
    store.ingest_normalized_flows(flows)

    assert store.get_normalized_flows(limit=2) == flows[1:]


def test_resolved_hubble_flows_are_projected_as_portal_policy_evidence(tmp_path):
    store = Store(tmp_path / "telemetry.sqlite")
    with store.connect() as database:
        for tenant_id, tenant_name in (("college-id", "College"), ("hospital-id", "Hospital")):
            database.execute(
                "INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,0)",
                (tenant_id, tenant_name, ""),
            )
        for identity, template in (
            (COLLEGE_WEB, "web"),
            (COLLEGE_API, "api"),
            (HOSPITAL_API, "api"),
        ):
            database.execute(
                """INSERT INTO workloads
                   (id,tenant_id,name,template,desired,observed,created)
                   VALUES (?,?,?,?,?,?,0)""",
                (
                    identity.workload_id,
                    identity.tenant_id,
                    identity.workload_name,
                    template,
                    "running",
                    "running",
                ),
            )
    allowed = normalize_hubble_flow(
        payload("allowed-1", "2026-11-13T09:00:01Z"),
        index(),
    )
    denied = normalize_hubble_flow(
        payload(
            "denied-1",
            "2026-11-13T09:00:02Z",
            destination=HOSPITAL_API,
            verdict="DROPPED",
        ),
        index(),
    )
    store.ingest_normalized_flows([allowed, denied])

    evidence = store.get_normalized_traffic()

    assert [(event["decision"], event["reason"]) for event in evidence] == [
        ("allowed", "approved-intent"),
        ("denied", "cross-tenant"),
    ]


def test_api_lifespan_ingests_configured_hubble_export(tmp_path):
    export = tmp_path / "hubble-events.log"
    export.write_text(
        json.dumps(payload("background", "2026-11-13T09:00:01Z")) + "\n",
        encoding="utf-8",
    )
    app = create_app(
        Settings(
            tmp_path / "api.sqlite",
            origin="http://testserver",
            secure_cookie=False,
            hubble_export=export,
        ),
    )
    with app.state.store.connect() as database:
        database.execute(
            "INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
            ("college-id", "College", "", time.time()),
        )
        for identity, template in (
            (COLLEGE_WEB, "web"),
            (COLLEGE_API, "api"),
        ):
            database.execute(
                """INSERT INTO workloads
                   (id,tenant_id,name,template,desired,observed,created)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    identity.workload_id,
                    identity.tenant_id,
                    identity.workload_name,
                    template,
                    "running",
                    "running",
                    time.time(),
                ),
            )

    with TestClient(app) as client:
        deadline = time.monotonic() + 3
        status = None
        while time.monotonic() < deadline:
            status = client.get("/api/health").json()["telemetry"]
            if status["accepted"] == 1:
                break
            time.sleep(0.05)
        assert status["enabled"] is True
        assert status["accepted"] == 1
        assert status["rejected"] == 0
        assert status["last_error"] is None
    stored = app.state.store.get_normalized_flows()
    assert len(stored) == 1
    assert stored[0].event_id == "background"
    assert stored[0].identity_status == "resolved"
