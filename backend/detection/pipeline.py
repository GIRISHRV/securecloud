"""Temporal graph scoring pipeline for live Hubble evidence."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from backend.telemetry.schema import NormalizedFlow
from backend.telemetry.windows import build_graph_snapshots
from backend.detection.volume import expected_rates, volume_spike, warming_up

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
    accumulated_risk: float = 0.0
    baseline_score: float = 0.0
    response: str = "alert"


@dataclass(frozen=True)
class GraphRiskObservation:
    model_version: str
    window_start: float
    window_end: float
    source_id: str
    destination_id: str
    anomaly_score: float
    accumulated_risk: float
    baseline_score: float
    threshold: float
    corroborated: bool
    response: str


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
            if flow.policy_denied
            or (
                flow.cross_tenant is True
                and (flow.source.workload_id, flow.destination.workload_id)
                not in approved_edges
            )
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
                source_destinations.setdefault(edge.source_id, set())
                source_ports.setdefault(edge.source_id, set())
                # Fan-out evidence counts only unapproved or denied edges: calling several
                # approved services (e.g. the shared platform) is normal, not scanning.
                if (edge.source_id, edge.destination_id) in approved_edges and not edge.denied_count:
                    continue
                source_destinations[edge.source_id].add(edge.destination_id)
                source_ports[edge.source_id].update(edge.destination_ports)
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
                    "cross_tenant": edge.cross_tenant
                    and (edge.source_id, edge.destination_id) not in approved_edges,
                    "policy_denied": any(flow.policy_denied for flow in matching),
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

    def __init__(
        self,
        checkpoint: Path,
        *,
        window_seconds: int = 30,
        ewma_alpha: float = 0.45,
    ):
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.checkpoint = checkpoint.resolve(strict=True)
        self.window_seconds = window_seconds
        if not 0 < ewma_alpha <= 1:
            raise ValueError("ewma_alpha must be in (0, 1]")
        self.ewma_alpha = ewma_alpha
        self._engines: dict[tuple, TemporalGraphEngine] = {}
        self.last_observations: tuple[GraphRiskObservation, ...] = ()

    def _engine(
        self,
        workloads: list[WorkloadDescriptor],
        approved_edges: set[tuple[str, str]],
    ) -> TemporalGraphEngine:
        signature = (
            tuple(sorted(
            (item.id, item.tenant_id, item.template, item.running, item.quarantined)
            for item in workloads
            )),
            tuple(sorted(approved_edges)),
        )
        if signature not in self._engines:
            self._engines[signature] = TemporalGraphEngine.from_checkpoint(
                self.checkpoint, workloads, approved_edges=approved_edges
            )
        return self._engines[signature]

    def validate(
        self,
        workloads: list[WorkloadDescriptor],
        approved_edges: set[tuple[str, str]] | None = None,
    ) -> None:
        """Eagerly validate weights when an active lab already has workloads."""
        if workloads:
            self._engine(workloads, approved_edges or set())

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
        security_relevant = [
            flow for flow in resolved
            if flow.policy_denied
            or (
                flow.cross_tenant is True
                and (flow.source.workload_id, flow.destination.workload_id)
                not in approved_edges
            )
        ]
        if not workloads or not resolved:
            self.last_observations = ()
            return ()
        if security_relevant:
            cutoff = min(flow.observed_at for flow in security_relevant)
            reviewed_benign = [
                flow for flow in resolved
                if flow.observed_at < cutoff
                and flow.verdict == "forwarded"
                and (flow.source.workload_id, flow.destination.workload_id)
                in approved_edges
            ]
            history = build_graph_snapshots(
                reviewed_benign, window_seconds=self.window_seconds
            )
            inference_snapshots = build_graph_snapshots(
                [flow for flow in resolved if flow.observed_at >= cutoff],
                window_seconds=self.window_seconds,
            )
        else:
            snapshots = build_graph_snapshots(
                resolved, window_seconds=self.window_seconds
            )
            history = snapshots[:-1]
            inference_snapshots = snapshots[-1:]
        if not history or not inference_snapshots:
            self.last_observations = ()
            return ()
        engine = self._engine(workloads, approved_edges)
        hidden = engine.prime(history)
        created = {item.id: item.created for item in workloads}
        described = {item.id: item for item in workloads}

        def template_intent(source: str, destination: str) -> bool:
            """Same-tenant web->api / api->database: the shop template's own declared paths. A new
            shop's pods serve traffic seconds before they are marked running (and approved)."""
            left, right = described.get(source), described.get(destination)
            return bool(left and right and left.tenant_id == right.tenant_id
                        and (left.template, right.template) in {("web", "api"), ("api", "database")})
        usual_rates = expected_rates(history, created)
        baseline = EdgeFrequencyBaseline(
            anomaly_threshold=max(0.000_001, float(engine.threshold))
        )
        baseline.fit(history)
        findings: list[GraphRiskFinding] = []
        observations: list[GraphRiskObservation] = []
        accumulated_by_source: dict[str, float] = {}
        for snapshot in inference_snapshots:
            source_destinations: dict[str, set[str]] = {}
            source_ports: dict[str, set[int]] = {}
            for edge in snapshot.edges:
                source_destinations.setdefault(edge.source_id, set())
                source_ports.setdefault(edge.source_id, set())
                # Fan-out evidence counts only unapproved or denied edges: calling several
                # approved services (e.g. the shared platform) is normal, not scanning.
                if (edge.source_id, edge.destination_id) in approved_edges and not edge.denied_count:
                    continue
                source_destinations[edge.source_id].add(edge.destination_id)
                source_ports[edge.source_id].update(edge.destination_ports)
            scores, hidden = engine.score(snapshot, hidden)
            baseline_by_edge = {
                (score.source_id, score.destination_id): score
                for score in baseline.score(snapshot)
            }
            score_by_edge = {
                (score.source_id, score.destination_id): score for score in scores
            }
            for edge in snapshot.edges:
                score = score_by_edge.get((edge.source_id, edge.destination_id))
                if score is None:
                    continue
                matching = [
                    flow for flow in resolved
                    if snapshot.window_start <= flow.observed_at < snapshot.window_end
                    and flow.source.workload_id == edge.source_id
                    and flow.destination.workload_id == edge.destination_id
                ]
                facts = {
                    "cross_tenant": edge.cross_tenant
                    and (edge.source_id, edge.destination_id) not in approved_edges,
                    "policy_denied": any(flow.policy_denied for flow in matching),
                    "horizontal_fanout": len(source_destinations[edge.source_id]) >= 3,
                    "vertical_port_fanout": len(source_ports[edge.source_id]) >= 3,
                    # A normally quiet approved path suddenly carrying a burst (see detection.volume).
                    # Not for a newly provisioned workload: it has no usual rate yet (see WARMUP_SECONDS).
                    "volume_spike": (edge.source_id, edge.destination_id) in approved_edges
                    and not warming_up((edge.source_id, edge.destination_id), created, snapshot.window_start)
                    and volume_spike(edge.flow_count, usual_rates.get((edge.source_id, edge.destination_id), 0.0)),
                }
                if not matching:
                    continue
                learned = score.anomaly_score
                # Cold start: a just-provisioned workload has no temporal history, so the link
                # predictor's novelty for it is undefined, not evidence. Its approved, undenied paths
                # (the template's declared intents) do not contribute novelty during the warm-up;
                # anything unapproved, denied or cross-tenant still carries the fact-based floors.
                declared = (edge.source_id, edge.destination_id) in approved_edges or template_intent(edge.source_id, edge.destination_id)
                if (warming_up((edge.source_id, edge.destination_id), created, snapshot.window_start)
                        and declared and not edge.denied_count):
                    learned = 0.0
                # Risk is the higher of the link score and the volume rule.
                anomaly = max(learned, 1.0 if facts["volume_spike"] else 0.0)
                prior = accumulated_by_source.get(edge.source_id, anomaly)
                accumulated = (
                    self.ewma_alpha * anomaly
                    + (1 - self.ewma_alpha) * prior
                )
                accumulated_by_source[edge.source_id] = accumulated
                corroborated = any(facts.values())
                baseline_score = baseline_by_edge[(edge.source_id, edge.destination_id)].anomaly_score
                response = (
                    "containment-recommended"
                    if accumulated >= float(engine.threshold) and corroborated
                    else "observe"
                )
                observations.append(GraphRiskObservation(
                    model_version=TEMPORAL_MODEL_VERSION,
                    window_start=snapshot.window_start,
                    window_end=snapshot.window_end,
                    source_id=edge.source_id,
                    destination_id=edge.destination_id,
                    anomaly_score=anomaly,
                    accumulated_risk=accumulated,
                    baseline_score=baseline_score,
                    threshold=float(engine.threshold),
                    corroborated=corroborated,
                    response=response,
                ))
                if response != "containment-recommended":
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
                    anomaly_score=anomaly,
                    threshold=float(engine.threshold),
                    supporting_facts=facts,
                    event_ids=tuple(flow.event_id for flow in matching),
                    created_at=max(flow.observed_at for flow in matching),
                    accumulated_risk=accumulated,
                    baseline_score=baseline_score,
                    response=response,
                ))
        self.last_observations = tuple(observations)
        return tuple(findings)
