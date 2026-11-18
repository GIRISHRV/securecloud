from backend.detection import EdgeFrequencyBaseline, EdgeFrequencyDetectionPipeline
from backend.telemetry import NormalizedFlow, WorkloadIdentity, build_graph_snapshots


TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
WEB = WorkloadIdentity(TENANT_A, "web", "web")
API = WorkloadIdentity(TENANT_A, "api", "api")
DATABASE = WorkloadIdentity(TENANT_A, "database", "database")
OTHER_API = WorkloadIdentity(TENANT_B, "other-api", "other-api")


def flow(identifier, at, source, destination):
    return NormalizedFlow(
        event_id=identifier,
        observed_at=at,
        source=source,
        destination=destination,
        identity_status="resolved",
        verdict="forwarded",
        drop_reason=None,
        protocol="tcp",
        destination_port=8080,
        node_name="node",
    )


def test_frequency_baseline_scores_unseen_edges_higher_than_normal_edges():
    training = build_graph_snapshots(
        [
            flow("normal-1", 1, WEB, API),
            flow("normal-2", 31, WEB, API),
            flow("normal-3", 61, WEB, API),
            flow("database-1", 2, API, DATABASE),
            flow("database-2", 32, API, DATABASE),
        ],
    )
    baseline = EdgeFrequencyBaseline(anomaly_threshold=0.7)
    baseline.fit(training)
    observed = build_graph_snapshots(
        [
            flow("normal-test", 91, WEB, API),
            flow("novel-test", 92, WEB, OTHER_API),
        ],
    )[0]
    scores = {
        (score.source_id, score.destination_id): score
        for score in baseline.score(observed)
    }
    normal = scores[("web", "api")]
    novel = scores[("web", "other-api")]
    assert normal.anomaly_score < novel.anomaly_score
    assert normal.is_anomalous is False
    assert novel.is_anomalous is True
    assert novel.observations == 0
    assert novel.cross_tenant is True


def test_frequency_baseline_requires_reviewed_training_snapshots():
    baseline = EdgeFrequencyBaseline()
    try:
        baseline.fit([])
    except ValueError as error:
        assert "benign" in str(error)
    else:
        raise AssertionError("Empty training data must be rejected")


def test_temporal_pipeline_correlates_unseen_edge_with_explicit_security_facts():
    benign = [
        flow("normal-1", 1, WEB, API),
        flow("normal-2", 31, WEB, API),
        flow("normal-3", 61, WEB, API),
    ]
    denied = NormalizedFlow(
        event_id="cross-tenant-denial",
        observed_at=91,
        source=WEB,
        destination=OTHER_API,
        identity_status="resolved",
        verdict="dropped",
        drop_reason="POLICY_DENIED",
        protocol="tcp",
        destination_port=8080,
        node_name="node",
    )

    findings = EdgeFrequencyDetectionPipeline(anomaly_threshold=0.7).analyze(
        [*benign, denied],
        {("web", "api")},
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.model_version == "edge-frequency-v1"
    assert finding.source_id == "web"
    assert finding.destination_id == "other-api"
    assert finding.anomaly_score == 0.8
    assert finding.predicted_probability == 0.2
    assert finding.supporting_facts["cross_tenant"] is True
    assert finding.supporting_facts["policy_denied"] is True
    assert finding.event_ids == ("cross-tenant-denial",)


def test_temporal_pipeline_is_inconclusive_without_earlier_benign_training():
    denied = NormalizedFlow(
        event_id="first-event-is-denied",
        observed_at=1,
        source=WEB,
        destination=OTHER_API,
        identity_status="resolved",
        verdict="dropped",
        drop_reason="POLICY_DENIED",
        protocol="tcp",
        destination_port=8080,
        node_name="node",
    )
    assert EdgeFrequencyDetectionPipeline().analyze(
        [denied],
        {("web", "api")},
    ) == ()
