import pytest
from dataclasses import replace

torch = pytest.importorskip("torch")

from backend.detection.pipeline import TemporalGraphDetectionPipeline
from backend.detection.temporal_graph import TemporalGraphEngine, WorkloadDescriptor
from backend.experiments.scenarios import benign_training_flows, build_scenario
from backend.telemetry.windows import build_graph_snapshots


WORKLOADS = [
    WorkloadDescriptor("college-web", "college", "web"),
    WorkloadDescriptor("college-api", "college", "api"),
    WorkloadDescriptor("college-database", "college", "database"),
    WorkloadDescriptor("hospital-web", "hospital", "web"),
    WorkloadDescriptor("hospital-api", "hospital", "api"),
    WorkloadDescriptor("hospital-database", "hospital", "database"),
    WorkloadDescriptor("college-reporting-web", "college", "web"),
    WorkloadDescriptor("college-reporting-api", "college", "api"),
]


def test_temporal_graph_training_is_chronological_and_scores_edges():
    snapshots = build_graph_snapshots(benign_training_flows(11), window_seconds=30)
    engine = TemporalGraphEngine(WORKLOADS, hidden_channels=8, seed=11)
    result = engine.fit(snapshots, seed=11, epochs=5)
    assert result.training_windows == 12
    assert result.calibration_windows == 4
    assert result.test_windows == 4
    assert 0.5 <= result.threshold <= 0.99

    hidden = engine.prime(snapshots)
    scenario = build_scenario("cross_tenant_attempt", 11, 0)
    observed = build_graph_snapshots(scenario.flows, window_seconds=30)[0]
    scores, next_hidden = engine.score(observed, hidden)
    assert scores[0].source_id == "college-web"
    assert scores[0].destination_id == "hospital-api"
    assert 0 <= scores[0].probability <= 1
    assert next_hidden.shape == hidden.shape


def test_temporal_graph_requires_enough_reviewed_history():
    engine = TemporalGraphEngine(WORKLOADS, hidden_channels=4, seed=1)
    with pytest.raises(ValueError, match="ten chronological"):
        engine.fit([], seed=1, epochs=1)


def test_temporal_graph_initialization_is_seeded():
    first = TemporalGraphEngine(WORKLOADS, hidden_channels=4, seed=29)
    second = TemporalGraphEngine(WORKLOADS, hidden_channels=4, seed=29)
    assert all(
        torch.equal(left, right)
        for left, right in zip(first.model.parameters(), second.model.parameters())
    )


def test_checkpoint_load_and_live_pipeline_preserve_model_evidence(tmp_path):
    history_flows = benign_training_flows(11)
    history = build_graph_snapshots(history_flows, window_seconds=30)
    engine = TemporalGraphEngine(WORKLOADS, hidden_channels=8, seed=11)
    result = engine.fit(history, seed=11, epochs=5)
    result = replace(result, threshold=0.0)
    engine.threshold = 0.0
    checkpoint = tmp_path / "temporal.pt"
    torch.save(
        {"state_dict": engine.model.state_dict(), "artifact": engine.artifact(result)},
        checkpoint,
    )

    loaded = TemporalGraphEngine.from_checkpoint(checkpoint, WORKLOADS)
    assert loaded.threshold == result.threshold
    assert all(
        torch.equal(left, right)
        for left, right in zip(engine.model.parameters(), loaded.model.parameters())
    )

    scenario = build_scenario("cross_tenant_attempt", 11, 0)
    pipeline = TemporalGraphDetectionPipeline(checkpoint)
    findings = pipeline.analyze(
        [*history_flows, *scenario.flows],
        set(scenario.approved_edges),
        WORKLOADS,
    )
    assert findings
    assert all(item.model_version == "gconvgru-link-v1" for item in findings)
    assert all(item.supporting_facts["cross_tenant"] for item in findings)
    assert all(0 <= item.predicted_probability <= 1 for item in findings)


def test_checkpoint_loader_rejects_non_checkpoint(tmp_path):
    invalid = tmp_path / "invalid.pt"
    invalid.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="cannot be loaded safely"):
        TemporalGraphEngine.from_checkpoint(invalid, WORKLOADS)


def test_checkpoint_ignores_tenants_outside_its_calibrated_lab(tmp_path):
    history = build_graph_snapshots(benign_training_flows(19), window_seconds=30)
    engine = TemporalGraphEngine(WORKLOADS, hidden_channels=4, seed=19)
    result = engine.fit(history, seed=19, epochs=1)
    checkpoint = tmp_path / "lab-model.pt"
    torch.save(
        {"state_dict": engine.model.state_dict(), "artifact": engine.artifact(result)},
        checkpoint,
    )
    loaded = TemporalGraphEngine.from_checkpoint(
        checkpoint,
        [*WORKLOADS, WorkloadDescriptor("testing-web", "testing", "web")],
    )
    assert "testing-web" not in loaded.tensorizer.index
