import json

import pytest

from backend.experiments.runner import EvaluationConfig, run_evaluation
from backend.experiments.live_runner import distribution, validate_loopback_url
from backend.experiments.metrics import (
    ScoredLabel,
    average_precision,
    classification_metrics,
    wilson_interval,
)
from backend.experiments.scenarios import build_scenario, scenario_ids


def test_metrics_use_defined_denominators_and_average_precision():
    items = [
        ScoredLabel(0.9, True, True),
        ScoredLabel(0.8, False, True),
        ScoredLabel(0.7, True, False),
        ScoredLabel(0.1, False, False),
    ]
    metrics = classification_metrics(items)
    assert metrics["tp"] == metrics["fp"] == metrics["fn"] == metrics["tn"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert average_precision(items) == pytest.approx((1 + 2 / 3) / 2)
    low, high = wilson_interval(50, 100)
    assert low == pytest.approx(0.4038, abs=0.001)
    assert high == pytest.approx(0.5962, abs=0.001)


def test_scenario_catalog_is_allowlisted_and_deterministic():
    assert len(scenario_ids()) == 13
    first = build_scenario("horizontal_scan", 11, 0)
    second = build_scenario("horizontal_scan", 11, 0)
    assert first == second
    assert first.malicious is True
    assert all(flow.drop_reason == "POLICY_DENIED" for flow in first.flows)
    with pytest.raises(ValueError, match="allowlisted"):
        build_scenario("https://external.example", 11, 0)


def test_live_runner_rejects_external_targets_and_credentials():
    assert validate_loopback_url("http://127.0.0.1:8091") == "http://127.0.0.1:8091"
    with pytest.raises(ValueError, match="loopback"):
        validate_loopback_url("https://example.com")
    with pytest.raises(ValueError, match="loopback"):
        validate_loopback_url("http://user:password@127.0.0.1:8091")
    observed = distribution([1.0, 2.0, 3.0, 4.0])
    assert observed["median"] == 2.5
    assert observed["p95"] == 4.0


def test_evaluation_exports_raw_ground_truth_without_fake_model_metrics(tmp_path):
    output = tmp_path / "evaluation"
    result = run_evaluation(EvaluationConfig(
        output, repetitions=2, seeds=(11, 29), include_temporal=False
    ))

    assert (output / "events.jsonl").is_file()
    assert (output / "predictions.jsonl").is_file()
    assert (output / "runs.csv").is_file()
    assert len(result["summary"]) == (len(scenario_ids()) + 1) * 2
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["configurations"]["temporal_graph_gconvgru"]["implemented"] is False
    assert manifest["configurations"]["live_containment"]["implemented"] is False

    summaries = {
        row["scenario_id"]: row
        for row in result["summary"]
        if row["configuration"] == "edge_frequency_baseline"
    }
    assert summaries["cross_tenant_attempt"]["prevention_rate"] == 1.0
    assert summaries["suspicious_approved_path"]["prevention_rate"] == 0.0
    assert summaries["new_approved_deployment"]["false_positive_rate"] == 0.0
