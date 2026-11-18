"""Deterministic event-time graph windows for baseline and learned detectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import Iterable

from .schema import NormalizedFlow


@dataclass(frozen=True)
class GraphEdge:
    source_id: str
    destination_id: str
    flow_count: int
    allowed_count: int
    denied_count: int
    destination_ports: tuple[int, ...]
    protocols: tuple[str, ...]
    cross_tenant: bool


@dataclass(frozen=True)
class GraphSnapshot:
    window_start: float
    window_end: float
    node_ids: tuple[str, ...]
    edges: tuple[GraphEdge, ...]
    event_ids: tuple[str, ...]
    inconclusive_count: int


@dataclass
class _EdgeAccumulator:
    source_id: str
    destination_id: str
    cross_tenant: bool
    flow_count: int = 0
    allowed_count: int = 0
    denied_count: int = 0
    ports: set[int] = field(default_factory=set)
    protocols: set[str] = field(default_factory=set)

    def add(self, flow: NormalizedFlow):
        self.flow_count += 1
        self.allowed_count += int(flow.verdict == "forwarded")
        self.denied_count += int(flow.verdict == "dropped")
        if flow.destination_port is not None:
            self.ports.add(flow.destination_port)
        if flow.protocol is not None:
            self.protocols.add(flow.protocol)

    def freeze(self) -> GraphEdge:
        return GraphEdge(
            source_id=self.source_id,
            destination_id=self.destination_id,
            flow_count=self.flow_count,
            allowed_count=self.allowed_count,
            denied_count=self.denied_count,
            destination_ports=tuple(sorted(self.ports)),
            protocols=tuple(sorted(self.protocols)),
            cross_tenant=self.cross_tenant,
        )


def build_graph_snapshots(
    flows: Iterable[NormalizedFlow],
    *,
    window_seconds: int = 30,
) -> list[GraphSnapshot]:
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")

    unique: dict[str, NormalizedFlow] = {}
    for flow in sorted(flows, key=lambda item: (item.observed_at, item.event_id)):
        unique.setdefault(flow.event_id, flow)

    windows: dict[float, list[NormalizedFlow]] = {}
    for flow in unique.values():
        start = floor(flow.observed_at / window_seconds) * window_seconds
        windows.setdefault(float(start), []).append(flow)

    snapshots: list[GraphSnapshot] = []
    for start in sorted(windows):
        events = sorted(windows[start], key=lambda item: (item.observed_at, item.event_id))
        edges: dict[tuple[str, str], _EdgeAccumulator] = {}
        nodes: set[str] = set()
        inconclusive = 0
        for flow in events:
            if (
                flow.identity_status != "resolved"
                or flow.source is None
                or flow.destination is None
                or flow.verdict == "unknown"
            ):
                inconclusive += 1
                continue
            source_id = flow.source.workload_id
            destination_id = flow.destination.workload_id
            nodes.update((source_id, destination_id))
            key = (source_id, destination_id)
            edge = edges.setdefault(
                key,
                _EdgeAccumulator(
                    source_id,
                    destination_id,
                    flow.source.tenant_id != flow.destination.tenant_id,
                ),
            )
            edge.add(flow)
        snapshots.append(
            GraphSnapshot(
                window_start=start,
                window_end=start + window_seconds,
                node_ids=tuple(sorted(nodes)),
                edges=tuple(edges[key].freeze() for key in sorted(edges)),
                event_ids=tuple(flow.event_id for flow in events),
                inconclusive_count=inconclusive,
            ),
        )
    return snapshots
