from backend.detection.pipeline import GraphRiskObservation
from backend.store import Store


def observation(index: int, score: float, response: str = "observe"):
    return GraphRiskObservation(
        model_version="test-model",
        window_start=float(index),
        window_end=float(index + 1),
        source_id="source",
        destination_id=f"destination-{index}",
        anomaly_score=score,
        accumulated_risk=score,
        baseline_score=0.1,
        threshold=0.5,
        corroborated=response == "containment-recommended",
        response=response,
    )


def test_risk_history_keeps_high_risk_evidence_with_recent_normal_windows(tmp_path):
    store = Store(tmp_path / "risk-history.sqlite")
    with store.connect() as database:
        database.execute(
            "INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
            ("tenant", "Tenant", "", 1.0),
        )
        for workload_id in ["source", *[f"destination-{index}" for index in range(131)]]:
            database.execute(
                """INSERT INTO workloads
                   (id,tenant_id,name,template,desired,observed,created)
                   VALUES(?,?,?,?,?,?,?)""",
                (workload_id, "tenant", workload_id, "api", "running", "running", 1.0),
            )

    store.record_risk_observations(
        [observation(0, 0.95, "containment-recommended")]
        + [observation(index, 0.00012) for index in range(1, 131)]
    )

    history = store.risk_observations(limit=20)

    assert len(history) == 20
    assert any(item["anomalyScore"] == 0.95 for item in history)
    assert any(item["windowStart"] == 130.0 for item in history)
