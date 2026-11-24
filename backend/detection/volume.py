"""Volume rule for abuse of an approved path.

The temporal model is a link predictor: it scores how unexpected it is that two workloads
talk at all, so a flood over an approved, already-known link never looks anomalous to it.
This rule covers that gap with a per-edge rate check.

It flags only a *normally quiet* approved path that suddenly carries a burst. A busy path
(a storefront calling its order API) can surge legitimately, for example during a sale, and
volume alone cannot tell that surge from abuse, so busy paths are deliberately not flagged.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from backend.telemetry.windows import GraphSnapshot

QUIET_EXPECTED = 1.5   # a path whose median connections per window is below this is "quiet"
MIN_BURST = 20         # connections in one window before a burst counts
SPIKE_RATIO = 5.0      # burst must also be this many times the path's usual rate


def expected_rates(history: list[GraphSnapshot]) -> dict[tuple[str, str], float]:
    """Median connections per window for every edge seen in the history (windows without it = 0).

    The median, not the mean: one earlier burst must not make a quiet path look busy, or a
    second flood shortly after the first would slip through."""
    if not history:
        return {}
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(history))
    for position, snapshot in enumerate(history):
        for edge in snapshot.edges:
            counts[(edge.source_id, edge.destination_id)][position] += edge.flow_count
    return {edge: float(median(values)) for edge, values in counts.items()}


def volume_spike(flow_count: int, expected: float) -> bool:
    return expected < QUIET_EXPECTED and flow_count >= MIN_BURST and flow_count >= SPIKE_RATIO * max(expected, 1.0)
