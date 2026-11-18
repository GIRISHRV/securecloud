"""Reproducible offline evaluation with raw, auditable outputs.

This runner measures implemented controls only. Live containment, recovery and
resource-overhead measurements belong to the isolated K3s runner and are never
inferred from these offline records.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from time import perf_counter

from backend.detection.edge_frequency import EdgeFrequencyBaseline
from backend.telemetry.windows import build_graph_snapshots

from .metrics import (
    ScoredLabel,
    classification_metrics,
    mean_or_none,
    safe_ratio,
    wilson_interval,
)
from .scenarios import WINDOW_SECONDS, benign_training_flows, build_scenario, scenario_ids


PROJECT_TITLE = "SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation"


@dataclass(frozen=True)
class EvaluationConfig:
    output_dir: Path
    repetitions: int = 30
    seeds: tuple[int, ...] = (11, 29, 47, 71, 101)
    anomaly_threshold: float = 0.6
    temporal_epochs: int = 80
    temporal_hidden_channels: int = 16
    include_temporal: bool = True

    def __post_init__(self):
        if self.repetitions <= 0 or not self.seeds:
            raise ValueError("Evaluation requires positive repetitions and at least one seed")
        if not 0 < self.anomaly_threshold <= 1:
            raise ValueError("anomaly_threshold must be in (0, 1]")
        if self.temporal_epochs <= 0 or self.temporal_hidden_channels <= 0:
            raise ValueError("Temporal model dimensions and epochs must be positive")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _edge_labels(scenario, snapshot) -> dict[tuple[str, str], bool]:
    malicious_ids = scenario.malicious_event_ids.intersection(snapshot.event_ids)
    malicious_edges = {
        (flow.source.workload_id, flow.destination.workload_id)
        for flow in scenario.flows
        if flow.event_id in malicious_ids and flow.source and flow.destination
    }
    return {
        (edge.source_id, edge.destination_id): (edge.source_id, edge.destination_id) in malicious_edges
        for edge in snapshot.edges
    }


def _has_security_fact(scenario, snapshot, source_id: str, destination_id: str) -> bool:
    event_ids = set(snapshot.event_ids)
    matching = [
        flow for flow in scenario.flows
        if flow.event_id in event_ids
        and flow.source
        and flow.destination
        and flow.source.workload_id == source_id
        and flow.destination.workload_id == destination_id
    ]
    source_edges = [edge for edge in snapshot.edges if edge.source_id == source_id]
    source_ports = {port for edge in source_edges for port in edge.destination_ports}
    return any((
        any(flow.cross_tenant for flow in matching),
        any(flow.policy_denied for flow in matching),
        len({edge.destination_id for edge in source_edges}) >= 3,
        len(source_ports) >= 3,
    ))


def run_evaluation(config: EvaluationConfig) -> dict:
    started = perf_counter()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    predictions: list[dict] = []
    run_rows: list[dict] = []
    temporal_artifacts: list[dict] = []

    temporal_types = None
    if config.include_temporal:
        import torch
        from backend.detection.temporal_graph import TemporalGraphEngine, WorkloadDescriptor

        temporal_types = (torch, TemporalGraphEngine, WorkloadDescriptor)

    for seed in config.seeds:
        training_flows = benign_training_flows(seed)
        training_snapshots = build_graph_snapshots(training_flows, window_seconds=WINDOW_SECONDS)
        fit_started = perf_counter()
        baseline = EdgeFrequencyBaseline(anomaly_threshold=config.anomaly_threshold)
        baseline.fit(training_snapshots)
        fit_ms = (perf_counter() - fit_started) * 1_000
        temporal_engine = None
        temporal_hidden = None
        temporal_result = None
        if temporal_types:
            torch, TemporalGraphEngine, WorkloadDescriptor = temporal_types
            descriptors = [
                WorkloadDescriptor("college-web", "college", "web"),
                WorkloadDescriptor("college-api", "college", "api"),
                WorkloadDescriptor("college-database", "college", "database"),
                WorkloadDescriptor("hospital-web", "hospital", "web"),
                WorkloadDescriptor("hospital-api", "hospital", "api"),
                WorkloadDescriptor("hospital-database", "hospital", "database"),
                WorkloadDescriptor("college-reporting-web", "college", "web"),
                WorkloadDescriptor("college-reporting-api", "college", "api"),
            ]
            temporal_engine = TemporalGraphEngine(
                descriptors,
                hidden_channels=config.temporal_hidden_channels,
                seed=seed,
            )
            temporal_result = temporal_engine.fit(
                training_snapshots,
                seed=seed,
                epochs=config.temporal_epochs,
            )
            temporal_hidden = temporal_engine.prime(training_snapshots)
            models_dir = config.output_dir / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            torch.save(
                {
                    "state_dict": temporal_engine.model.state_dict(),
                    "artifact": temporal_engine.artifact(temporal_result),
                },
                models_dir / f"temporal_graph_seed_{seed}.pt",
            )
            artifact = temporal_engine.artifact(temporal_result)
            (models_dir / f"temporal_graph_seed_{seed}.json").write_text(
                json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8"
            )
            temporal_artifacts.append(artifact)

        for repetition in range(config.repetitions):
            for scenario_id in scenario_ids():
                scenario = build_scenario(scenario_id, seed, repetition)
                run_id = f"seed-{seed}-rep-{repetition:02d}-{scenario_id}"
                first_malicious_at = min(
                    (flow.observed_at for flow in scenario.flows if flow.event_id in scenario.malicious_event_ids),
                    default=None,
                )
                prevented = 0
                for flow in scenario.flows:
                    malicious = flow.event_id in scenario.malicious_event_ids
                    prevented += int(
                        malicious
                        and flow.verdict == "dropped"
                        and flow.drop_reason == "POLICY_DENIED"
                    )
                    events.append({
                        "run_id": run_id,
                        "seed": seed,
                        "repetition": repetition,
                        "scenario_id": scenario.id,
                        "category": scenario.category,
                        "event_id": flow.event_id,
                        "observed_at": flow.observed_at,
                        "source_id": flow.source.workload_id,
                        "destination_id": flow.destination.workload_id,
                        "destination_port": flow.destination_port,
                        "verdict": flow.verdict,
                        "drop_reason": flow.drop_reason,
                        "ground_truth_malicious": malicious,
                    })

                snapshots = build_graph_snapshots(
                    scenario.flows, window_seconds=WINDOW_SECONDS
                )
                scored: list[ScoredLabel] = []
                first_detection_at: float | None = None
                inference_started = perf_counter()
                for snapshot in snapshots:
                    labels = _edge_labels(scenario, snapshot)
                    for score in baseline.score(snapshot):
                        label = labels[(score.source_id, score.destination_id)]
                        security_fact = _has_security_fact(
                            scenario, snapshot, score.source_id, score.destination_id
                        )
                        incident = score.is_anomalous and security_fact
                        item = ScoredLabel(
                            score.anomaly_score, label, incident
                        )
                        scored.append(item)
                        if label and item.predicted:
                            first_detection_at = min(
                                first_detection_at or snapshot.window_end,
                                snapshot.window_end,
                            )
                        predictions.append({
                            "run_id": run_id,
                            "configuration": "edge_frequency_baseline",
                            "scenario_id": scenario.id,
                            "window_start": snapshot.window_start,
                            "window_end": snapshot.window_end,
                            "source_id": score.source_id,
                            "destination_id": score.destination_id,
                            "score": score.anomaly_score,
                            "threshold": config.anomaly_threshold,
                            "raw_anomalous": score.is_anomalous,
                            "security_fact": security_fact,
                            "predicted_anomalous": incident,
                            "ground_truth_malicious": label,
                        })
                inference_ms = (perf_counter() - inference_started) * 1_000
                metrics = classification_metrics(scored)
                malicious_count = len(scenario.malicious_event_ids)
                run_rows.append({
                    "run_id": run_id,
                    "configuration": "edge_frequency_baseline",
                    "scenario_id": scenario.id,
                    "category": scenario.category,
                    "seed": seed,
                    "repetition": repetition,
                    "event_count": len(scenario.flows),
                    "malicious_event_count": malicious_count,
                    "prevented_event_count": prevented,
                    "prevention_rate": safe_ratio(prevented, malicious_count),
                    **metrics,
                    "detection_latency_seconds": (
                        first_detection_at - first_malicious_at
                        if first_detection_at is not None and first_malicious_at is not None
                        else None
                    ),
                    "training_time_ms": fit_ms,
                    "inference_time_ms": inference_ms,
                    "containment_time_ms": None,
                    "recovery_time_ms": None,
                    "measurement_scope": "offline",
                })
                if temporal_engine is not None and temporal_hidden is not None and temporal_result is not None:
                    temporal_scored: list[ScoredLabel] = []
                    temporal_first_detection: float | None = None
                    scenario_hidden = temporal_hidden.clone()
                    temporal_inference_started = perf_counter()
                    for snapshot in snapshots:
                        labels = _edge_labels(scenario, snapshot)
                        scores, scenario_hidden = temporal_engine.score(snapshot, scenario_hidden)
                        for score in scores:
                            label = labels[(score.source_id, score.destination_id)]
                            security_fact = _has_security_fact(
                                scenario, snapshot, score.source_id, score.destination_id
                            )
                            incident = score.is_anomalous and security_fact
                            temporal_scored.append(
                                ScoredLabel(score.anomaly_score, label, incident)
                            )
                            if label and incident:
                                temporal_first_detection = min(
                                    temporal_first_detection or snapshot.window_end,
                                    snapshot.window_end,
                                )
                            predictions.append({
                                "run_id": run_id,
                                "configuration": "temporal_graph_gconvgru",
                                "scenario_id": scenario.id,
                                "window_start": snapshot.window_start,
                                "window_end": snapshot.window_end,
                                "source_id": score.source_id,
                                "destination_id": score.destination_id,
                                "score": score.anomaly_score,
                                "threshold": temporal_result.threshold,
                                "raw_anomalous": score.is_anomalous,
                                "security_fact": security_fact,
                                "predicted_anomalous": incident,
                                "ground_truth_malicious": label,
                            })
                    temporal_metrics = classification_metrics(temporal_scored)
                    run_rows.append({
                        "run_id": run_id,
                        "configuration": "temporal_graph_gconvgru",
                        "scenario_id": scenario.id,
                        "category": scenario.category,
                        "seed": seed,
                        "repetition": repetition,
                        "event_count": len(scenario.flows),
                        "malicious_event_count": malicious_count,
                        "prevented_event_count": prevented,
                        "prevention_rate": safe_ratio(prevented, malicious_count),
                        **temporal_metrics,
                        "detection_latency_seconds": (
                            temporal_first_detection - first_malicious_at
                            if temporal_first_detection is not None and first_malicious_at is not None
                            else None
                        ),
                        "training_time_ms": temporal_result.training_time_ms,
                        "inference_time_ms": (perf_counter() - temporal_inference_started) * 1_000,
                        "containment_time_ms": None,
                        "recovery_time_ms": None,
                        "measurement_scope": "offline",
                    })

    summary_rows: list[dict] = []
    detector_configurations = ["edge_frequency_baseline"]
    if config.include_temporal:
        detector_configurations.append("temporal_graph_gconvgru")
    for scenario_id in (*scenario_ids(), "ALL"):
        scenario_common = None
        for configuration in detector_configurations:
            selected = [
                row for row in run_rows
                if row["configuration"] == configuration
                and (scenario_id == "ALL" or row["scenario_id"] == scenario_id)
            ]
            combined = [
                ScoredLabel(
                    prediction["score"],
                    prediction["ground_truth_malicious"],
                    prediction["predicted_anomalous"],
                )
                for prediction in predictions
                if prediction["configuration"] == configuration
                and (scenario_id == "ALL" or prediction["scenario_id"] == scenario_id)
            ]
            metrics = classification_metrics(combined)
            malicious = sum(row["malicious_event_count"] for row in selected)
            prevented = sum(row["prevented_event_count"] for row in selected)
            prevention_low, prevention_high = wilson_interval(prevented, malicious)
            recall_low, recall_high = wilson_interval(metrics["tp"], metrics["tp"] + metrics["fn"])
            fpr_low, fpr_high = wilson_interval(metrics["fp"], metrics["fp"] + metrics["tn"])
            common = {
                "scenario_id": scenario_id,
                "category": "all" if scenario_id == "ALL" else selected[0]["category"],
                "runs": len(selected),
                "prevention_rate": safe_ratio(prevented, malicious),
                "prevention_rate_macro": mean_or_none([row["prevention_rate"] for row in selected]),
                "prevention_ci95_low": prevention_low,
                "prevention_ci95_high": prevention_high,
            }
            scenario_common = common
            summary_rows.append({
                "configuration": configuration,
                **common,
                **metrics,
                "recall_ci95_low": recall_low,
                "recall_ci95_high": recall_high,
                "false_positive_rate_ci95_low": fpr_low,
                "false_positive_rate_ci95_high": fpr_high,
                "mean_detection_latency_seconds": mean_or_none([row["detection_latency_seconds"] for row in selected]),
                "mean_training_time_ms": mean(row["training_time_ms"] for row in selected),
                "mean_inference_time_ms": mean(row["inference_time_ms"] for row in selected),
            })
        common = scenario_common
        summary_rows.append({
            "configuration": "static_policy",
            **common,
            "tp": None,
            "fp": None,
            "fn": None,
            "tn": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "false_positive_rate": None,
            "pr_auc_average_precision": None,
            "recall_ci95_low": None,
            "recall_ci95_high": None,
            "false_positive_rate_ci95_low": None,
            "false_positive_rate_ci95_high": None,
            "mean_detection_latency_seconds": None,
            "mean_training_time_ms": None,
            "mean_inference_time_ms": None,
        })

    manifest = {
        "project": PROJECT_TITLE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repetitions_per_seed": config.repetitions,
        "seeds": list(config.seeds),
        "scenario_ids": list(scenario_ids()),
        "window_seconds": WINDOW_SECONDS,
        "anomaly_threshold": config.anomaly_threshold,
        "configurations": {
            "static_policy": {
                "implemented": True,
                "measurement": "event verdicts in events.jsonl",
            },
            "edge_frequency_baseline": {
                "implemented": True,
                "measurement": "edge predictions in predictions.jsonl",
            },
            "temporal_graph_gconvgru": {
                "implemented": config.include_temporal,
                "reason": None if config.include_temporal else "Disabled for this evaluation run.",
                "artifacts": temporal_artifacts,
            },
            "live_containment": {
                "implemented": False,
                "reason": "Offline runner cannot measure cluster containment, recovery or resource overhead.",
            },
        },
        "elapsed_seconds": perf_counter() - started,
    }
    _write_jsonl(config.output_dir / "events.jsonl", events)
    _write_jsonl(config.output_dir / "predictions.jsonl", predictions)
    _write_csv(config.output_dir / "runs.csv", run_rows)
    _write_csv(config.output_dir / "summary.csv", summary_rows)
    (config.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    result = {"manifest": manifest, "summary": summary_rows}
    (config.output_dir / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the SecureCloud offline evaluation"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("runtime/experiments/offline")
    )
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[11, 29, 47, 71, 101]
    )
    parser.add_argument("--temporal-epochs", type=int, default=80)
    parser.add_argument("--skip-temporal", action="store_true")
    arguments = parser.parse_args()
    result = run_evaluation(EvaluationConfig(
        arguments.output,
        arguments.repetitions,
        tuple(arguments.seeds),
        temporal_epochs=arguments.temporal_epochs,
        include_temporal=not arguments.skip_temporal,
    ))
    print(json.dumps({
        "output": str(arguments.output),
        "runs": arguments.repetitions * len(arguments.seeds) * len(scenario_ids()),
        "elapsed_seconds": result["manifest"]["elapsed_seconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
