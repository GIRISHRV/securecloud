"""Simple temporal-link baseline used for comparison with the learned model."""
from __future__ import annotations

from dataclasses import dataclass

from backend.telemetry.windows import GraphSnapshot


@dataclass(frozen=True)
class EdgeFrequencyScore:
    source_id: str
    destination_id: str
    predicted_probability: float
    anomaly_score: float
    is_anomalous: bool
    observations: int
    training_snapshots: int
    cross_tenant: bool


class EdgeFrequencyBaseline:
    """Estimate next-window edge likelihood from reviewed benign frequency."""

    def __init__(self, *, anomaly_threshold: float = 0.8, smoothing: float = 1.0):
        if not 0 < anomaly_threshold <= 1:
            raise ValueError("anomaly_threshold must be in (0, 1]")
        if smoothing <= 0:
            raise ValueError("smoothing must be positive")
        self.anomaly_threshold = anomaly_threshold
        self.smoothing = smoothing
        self.training_snapshots = 0
        self.edge_observations: dict[tuple[str, str], int] = {}

    def fit(self, snapshots: list[GraphSnapshot]) -> None:
        if not snapshots:
            raise ValueError("At least one benign snapshot is required")
        self.training_snapshots = len(snapshots)
        self.edge_observations = {}
        for snapshot in sorted(snapshots, key=lambda item: item.window_start):
            for edge in snapshot.edges:
                key = (edge.source_id, edge.destination_id)
                self.edge_observations[key] = self.edge_observations.get(key, 0) + 1

    def score(self, snapshot: GraphSnapshot) -> tuple[EdgeFrequencyScore, ...]:
        if self.training_snapshots == 0:
            raise RuntimeError("Fit the baseline before scoring")
        scores = []
        denominator = self.training_snapshots + (2 * self.smoothing)
        for edge in snapshot.edges:
            key = (edge.source_id, edge.destination_id)
            observations = self.edge_observations.get(key, 0)
            probability = (observations + self.smoothing) / denominator
            anomaly = 1.0 - probability
            scores.append(
                EdgeFrequencyScore(
                    source_id=edge.source_id,
                    destination_id=edge.destination_id,
                    predicted_probability=round(probability, 6),
                    anomaly_score=round(anomaly, 6),
                    is_anomalous=anomaly >= self.anomaly_threshold,
                    observations=observations,
                    training_snapshots=self.training_snapshots,
                    cross_tenant=edge.cross_tenant,
                ),
            )
        return tuple(scores)
