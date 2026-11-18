"""Temporal graph scoring pipeline for live Hubble evidence."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from backend.telemetry.schema import NormalizedFlow
from backend.telemetry.windows import build_graph_snapshots

from .edge_frequency import EdgeFrequencyBaseline
from .temporal_graph import (
    MODEL_VERSION as TEMPORAL_MODEL_VERSION,
    TemporalGraphEngine,
    WorkloadDescriptor,
)


MODEL_VERSION = "edge-frequency-v1"


@dataclass(frozen=True)
class GraphRiskFinding:
    id: str
    model_version: str
    window_start: float
    window_end: float
    source_id: str
    source_name: str
    source_tenant: str
    destination_id: str
    predicted_probability: float
    anomaly_score: float
    threshold: float
    supporting_facts: dict[str, bool]
    event_ids: tuple[str, ...]
    created_at: float


class EdgeFrequencyDetectionPipeline:
    """Compare observed security-relevant edges with reviewed approved traffic."""

    def __init__(self, *, anomaly_threshold: float = 0.6, window_seconds: int = 30):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.anomaly_threshold = anomaly_threshold
        self.window_seconds = window_seconds

    def analyze(
        self,
        flows: list[NormalizedFlow],
        approved_edges: set[tuple[str, str]],
    ) -> tuple[GraphRiskFinding, ...]:
        resolved = [
            flow for flow in flows
            if flow.identity_status == "resolved" and flow.source and flow.destination
        ]
        candidates = [
            flow for flow in resolved
            if flow.policy_denied or flow.cross_tenant is True
        ]
        if not candidates:
            return ()
        cutoff = min(flow.observed_at for flow in candidates)
        reviewed_benign = [
            flow for flow in resolved
            if flow.observed_at < cutoff
            and flow.verdict == "forwarded"
            and (flow.source.workload_id, flow.destination.workload_id) in approved_edges
        ]
        training = build_graph_snapshots(reviewed_benign, window_seconds=self.window_seconds)
        if not training:
            return ()
        baseline = EdgeFrequencyBaseline(anomaly_threshold=self.anomaly_threshold)
        baseline.fit(training)

        findings: list[GraphRiskFinding] = []
        for snapshot in build_graph_snapshots(candidates, window_seconds=self.window_seconds):
            source_destinations: dict[str, set[str]] = {}
            source_ports: dict[str, set[int]] = {}
            for edge in snapshot.edges:
                source_destinations.setdefault(edge.source_id, set()).add(edge.destination_id)
                source_ports.setdefault(edge.source_id, set()).update(edge.destination_ports)
            score_by_edge = {
                (score.source_id, score.destination_id): score
                for score in baseline.score(snapshot)
            }
            for edge in snapshot.edges:
                score = score_by_edge[(edge.source_id, edge.destination_id)]
                matching = [
                    flow for flow in candidates
                    if snapshot.window_start <= flow.observed_at < snapshot.window_end
                    and flow.source.workload_id == edge.source_id
                    and flow.destination.workload_id == edge.destination_id
                ]
                facts = {
                    "cross_tenant": edge.cross_tenant,
                    "policy_denied": edge.denied_count > 0,
                    "horizontal_fanout": len(source_destinations[edge.source_id]) >= 3,
                    "vertical_port_fanout": len(source_ports[edge.source_id]) >= 3,
                }
                if not score.is_anomalous or not any(facts.values()):
                    continue
                first = min(matching, key=lambda flow: (flow.observed_at, flow.event_id))
                finding_key = (
                    f"{MODEL_VERSION}|{snapshot.window_start}|{edge.source_id}|{edge.destination_id}"
                )
                findings.append(GraphRiskFinding(
                    id=sha256(finding_key.encode()).hexdigest()[:24],
                    model_version=MODEL_VERSION,
                    window_start=snapshot.window_start,
                    window_end=snapshot.window_end,
                    source_id=edge.source_id,
                    source_name=first.source.workload_name,
                    source_tenant=first.source.tenant_id,
                    destination_id=edge.destination_id,
                    predicted_probability=score.predicted_probability,
                    anomaly_score=score.anomaly_score,
                    threshold=self.anomaly_threshold,
                    supporting_facts=facts,
                    event_ids=tuple(flow.event_id for flow in matching),
                    created_at=max(flow.observed_at for flow in matching),
                ))
        return tuple(findings)


class TemporalGraphDetectionPipeline:
    """Score live windows with a calibrated GConvGRU and corroborating facts."""

    model_version = TEMPORAL_MODEL_VERSION

    def __init__(self, checkpoint: Path, *, window_seconds: int = 30):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.checkpoint = checkpoint.resolve(strict=True)
        self.window_seconds = window_seconds
        self._engines: dict[tuple[tuple[str, str, str, bool, bool], ...], TemporalGraphEngine] = {}

    def _engine(self, workloads: list[WorkloadDescriptor]) -> TemporalGraphEngine:
        signature = tuple(sorted(
            (item.id, item.tenant_id, item.template, item.running, item.quarantined)
            for item in workloads
        ))
        if signature not in self._engines:
            self._engines[signature] = TemporalGraphEngine.from_checkpoint(
                self.checkpoint, workloads
            )
        return self._engines[signature]

    def validate(self, workloads: list[WorkloadDescriptor]) -> None:
        """Eagerly validate weights when an active lab already has workloads."""
        if workloads:
            self._engine(workloads)

    def analyze(
        self,
        flows: list[NormalizedFlow],
        approved_edges: set[tuple[str, str]],
        workloads: list[WorkloadDescriptor],
    ) -> tuple[GraphRiskFinding, ...]:
        resolved = [
            flow for flow in flows
            if flow.identity_status == "resolved" and flow.source and flow.destination
        ]
        candidates = [
            flow for flow in resolved
            if flow.policy_denied or flow.cross_tenant is True
        ]
        if not candidates or not workloads:
            return ()
        cutoff = min(flow.observed_at for flow in candidates)
        reviewed_benign = [
            flow for flow in resolved
            if flow.observed_at < cutoff
            and flow.verdict == "forwarded"
            and (flow.source.workload_id, flow.destination.workload_id) in approved_edges
        ]
        history = build_graph_snapshots(reviewed_benign, window_seconds=self.window_seconds)
        if not history:
            return ()
        engine = self._engine(workloads)
        hidden = engine.prime(history)
        findings: list[GraphRiskFinding] = []
        for snapshot in build_graph_snapshots(candidates, window_seconds=self.window_seconds):
            source_destinations: dict[str, set[str]] = {}
            source_ports: dict[str, set[int]] = {}
            for edge in snapshot.edges:
                source_destinations.setdefault(edge.source_id, set()).add(edge.destination_id)
                source_ports.setdefault(edge.source_id, set()).update(edge.destination_ports)
            scores, hidden = engine.score(snapshot, hidden)
            score_by_edge = {
                (score.source_id, score.destination_id): score for score in scores
            }
            for edge in snapshot.edges:
                score = score_by_edge.get((edge.source_id, edge.destination_id))
                if score is None:
                    continue
                matching = [
                    flow for flow in candidates
                    if snapshot.window_start <= flow.observed_at < snapshot.window_end
                    and flow.source.workload_id == edge.source_id
                    and flow.destination.workload_id == edge.destination_id
                ]
                facts = {
                    "cross_tenant": edge.cross_tenant,
                    "policy_denied": edge.denied_count > 0,
                    "horizontal_fanout": len(source_destinations[edge.source_id]) >= 3,
                    "vertical_port_fanout": len(source_ports[edge.source_id]) >= 3,
                }
                if not matching or not score.is_anomalous or not any(facts.values()):
                    continue
                first = min(matching, key=lambda flow: (flow.observed_at, flow.event_id))
                finding_key = (
                    f"{TEMPORAL_MODEL_VERSION}|{snapshot.window_start}|"
                    f"{edge.source_id}|{edge.destination_id}"
                )
                findings.append(GraphRiskFinding(
                    id=sha256(finding_key.encode()).hexdigest()[:24],
                    model_version=TEMPORAL_MODEL_VERSION,
                    window_start=snapshot.window_start,
                    window_end=snapshot.window_end,
                    source_id=edge.source_id,
                    source_name=first.source.workload_name,
                    source_tenant=first.source.tenant_id,
                    destination_id=edge.destination_id,
                    predicted_probability=score.probability,
                    anomaly_score=score.anomaly_score,
                    threshold=float(engine.threshold),
                    supporting_facts=facts,
                    event_ids=tuple(flow.event_id for flow in matching),
                    created_at=max(flow.observed_at for flow in matching),
                ))
        return tuple(findings)
