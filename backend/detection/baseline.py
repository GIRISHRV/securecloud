"""Deterministic comparison detector for the local demonstrator.

This is intentionally not the planned temporal-graph model. The learned model
requires graph snapshots, chronological data splits, calibration, and a
persisted model artifact.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FlowRecord:
    id: str
    source_id: str
    destination_id: str
    source_tenant: str
    destination_tenant: str
    port: int
    at: float
    decision: str
    reason: str


@dataclass(frozen=True)
class AnomalyScore:
    score: float
    is_anomalous: bool
    reasons: list[str]
    supporting_facts: dict[str, Any]


class DenialBurstBaseline:
    """Flag a source after a bounded number of policy denials in one window."""

    def __init__(self, window_seconds: float = 60.0, denial_threshold: int = 3):
        if window_seconds <= 0 or denial_threshold <= 0:
            raise ValueError("Window and denial threshold must be positive")
        self.window_seconds = window_seconds
        self.denial_threshold = denial_threshold
        self.source_denials: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for source_id in list(self.source_denials):
            recent = [at for at in self.source_denials[source_id] if at >= cutoff]
            if recent:
                self.source_denials[source_id] = recent
            else:
                del self.source_denials[source_id]

    def score_event(self, flow: FlowRecord) -> AnomalyScore:
        """Score the current flow without mutating detector history."""
        self._prune(flow.at)
        recent_denials = len(self.source_denials.get(flow.source_id, []))
        if flow.decision == "denied":
            recent_denials += 1

        threshold_met = recent_denials >= self.denial_threshold
        reasons = []
        if threshold_met:
            reasons.append(
                f"Denial burst: {recent_denials} attempts in "
                f"{int(self.window_seconds)} seconds"
            )

        return AnomalyScore(
            score=round(min(1.0, recent_denials / self.denial_threshold), 4),
            is_anomalous=threshold_met and flow.decision == "denied",
            reasons=reasons,
            supporting_facts={
                "cross_tenant": flow.source_tenant != flow.destination_tenant,
                "policy_denied": flow.decision == "denied",
                "recent_denials_in_window": recent_denials,
                "denial_threshold": self.denial_threshold,
                "window_seconds": self.window_seconds,
                "port": flow.port,
            },
        )

    def record_flow(self, flow: FlowRecord) -> None:
        if flow.decision == "denied":
            self.source_denials.setdefault(flow.source_id, []).append(flow.at)
        self._prune(flow.at)
