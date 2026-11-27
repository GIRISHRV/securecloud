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
# A newly provisioned workload has no usual rate yet. Until it has run this long, the volume
# rule gives no verdict on its paths (the model and hard facts such as policy drops still apply).
WARMUP_SECONDS = 600.0


def expected_rates(history: list[GraphSnapshot], created: dict[str, float] | None = None) -> dict[tuple[str, str], float]:
    """Median connections per window for every edge seen in the history (windows without it = 0).

    The median, not the mean: one earlier burst must not make a quiet path look busy, or a
    second flood shortly after the first would slip through.

    With ``created`` (workload id -> provisioning time), only windows after both endpoints
    existed count. Windows from before a new shop existed are not evidence that its paths
    are quiet; counting them as zero made every new shop look like a burst."""
    if not history:
        return {}
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(history))
    for position, snapshot in enumerate(history):
        for edge in snapshot.edges:
            counts[(edge.source_id, edge.destination_id)][position] += edge.flow_count
    rates = {}
    for (source, destination), values in counts.items():
        born = max((created or {}).get(source, 0.0), (created or {}).get(destination, 0.0))
        lived = [value for value, snapshot in zip(values, history) if snapshot.window_end > born]
        if lived:
            rates[(source, destination)] = float(median(lived))
    return rates


def warming_up(workload_ids: tuple[str, ...], created: dict[str, float], at: float, warmup: float = WARMUP_SECONDS) -> bool:
    """True while any endpoint is younger than the warm-up period (no usual rate to judge by)."""
    return any(at - created.get(workload_id, 0.0) < warmup for workload_id in workload_ids)


def volume_spike(flow_count: int, expected: float) -> bool:
    return expected < QUIET_EXPECTED and flow_count >= MIN_BURST and flow_count >= SPIKE_RATIO * max(expected, 1.0)
