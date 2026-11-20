"""GConvGRU temporal link prediction for SecureCloud workload graphs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log1p
from pathlib import Path
import pickle
import random
from time import perf_counter

import torch
from torch import Tensor
from torch.nn import functional as F
from torch_geometric.nn import ChebConv

from backend.telemetry.windows import GraphSnapshot


MODEL_VERSION = "gconvgru-link-v2"
RELATION_FEATURE_NAMES = (
    "same_tenant",
    "approved_intent",
    "policy_denied_ratio",
    "cross_tenant",
)


@dataclass(frozen=True)
class WorkloadDescriptor:
    id: str
    tenant_id: str
    template: str
    running: bool = True
    quarantined: bool = False


@dataclass(frozen=True)
class TemporalTrainingResult:
    threshold: float
    training_windows: int
    calibration_windows: int
    test_windows: int
    epochs: int
    final_loss: float
    training_time_ms: float
    seed: int


@dataclass(frozen=True)
class TemporalEdgeScore:
    source_id: str
    destination_id: str
    probability: float
    anomaly_score: float
    is_anomalous: bool


class GConvGRUCell(torch.nn.Module):
    """API-compatible PyG implementation of the upstream GConvGRU cell."""

    def __init__(self, in_channels: int, out_channels: int, K: int = 2):
        super().__init__()
        arguments = dict(in_channels=in_channels, out_channels=out_channels, K=K, normalization="sym")
        self.out_channels = out_channels
        self.conv_x_z = ChebConv(**arguments)
        self.conv_x_r = ChebConv(**arguments)
        self.conv_x_h = ChebConv(**arguments)
        hidden = dict(in_channels=out_channels, out_channels=out_channels, K=K, normalization="sym")
        self.conv_h_z = ChebConv(**hidden)
        self.conv_h_r = ChebConv(**hidden)
        self.conv_h_h = ChebConv(**hidden)

    def forward(
        self,
        X: Tensor,
        edge_index: Tensor,
        edge_weight: Tensor | None = None,
        H: Tensor | None = None,
    ) -> Tensor:
        if H is None:
            H = torch.zeros(X.shape[0], self.out_channels, device=X.device, dtype=X.dtype)
        update = torch.sigmoid(
            self.conv_x_z(X, edge_index, edge_weight)
            + self.conv_h_z(H, edge_index, edge_weight)
        )
        reset = torch.sigmoid(
            self.conv_x_r(X, edge_index, edge_weight)
            + self.conv_h_r(H, edge_index, edge_weight)
        )
        candidate = torch.tanh(
            self.conv_x_h(X, edge_index, edge_weight)
            + self.conv_h_h(H * reset, edge_index, edge_weight)
        )
        return update * H + (1 - update) * candidate


class TemporalLinkPredictor(torch.nn.Module):
    def __init__(self, feature_count: int, hidden_channels: int = 16):
        super().__init__()
        self.encoder = GConvGRUCell(feature_count, hidden_channels, K=2)
        self.decoder = torch.nn.Sequential(
            torch.nn.Linear(hidden_channels * 2 + len(RELATION_FEATURE_NAMES), hidden_channels),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden_channels, 1),
        )

    def encode(self, x: Tensor, edge_index: Tensor, edge_weight: Tensor, hidden: Tensor | None) -> Tensor:
        return self.encoder(x, edge_index, edge_weight, hidden)

    def decode(self, hidden: Tensor, pairs: Tensor, relations: Tensor) -> Tensor:
        source = hidden[pairs[0]]
        destination = hidden[pairs[1]]
        return self.decoder(torch.cat((source, destination, relations), dim=1)).squeeze(1)


class GraphTensorizer:
    def __init__(
        self,
        workloads: list[WorkloadDescriptor],
        approved_edges: set[tuple[str, str]] | None = None,
    ):
        if not workloads or len({item.id for item in workloads}) != len(workloads):
            raise ValueError("Workload descriptors must be non-empty and unique")
        self.workloads = tuple(sorted(workloads, key=lambda item: item.id))
        self.index = {item.id: position for position, item in enumerate(self.workloads)}
        self.approved_edges = frozenset(approved_edges or set())
        self.templates = ("web", "api", "database")
        self.feature_names = (
            *(f"template:{name}" for name in self.templates),
            "inbound_log_count",
            "outbound_log_count",
            "denied_ratio",
            "unique_destination_count",
            "unique_destination_port_count",
            "running",
            "quarantined",
        )
        self.relation_feature_names = RELATION_FEATURE_NAMES

    def tensors(self, snapshot: GraphSnapshot) -> tuple[Tensor, Tensor, Tensor]:
        node_count = len(self.workloads)
        inbound = [0] * node_count
        outbound = [0] * node_count
        denied = [0] * node_count
        destinations = [set() for _ in range(node_count)]
        ports = [set() for _ in range(node_count)]
        message_edges: list[tuple[int, int, float]] = []
        for edge in snapshot.edges:
            if edge.source_id not in self.index or edge.destination_id not in self.index:
                continue
            source = self.index[edge.source_id]
            destination = self.index[edge.destination_id]
            outbound[source] += edge.flow_count
            inbound[destination] += edge.flow_count
            denied[source] += edge.denied_count
            destinations[source].add(destination)
            ports[source].update(edge.destination_ports)
            weight = log1p(edge.flow_count)
            message_edges.extend(((source, destination, weight), (destination, source, weight)))

        features = []
        for position, workload in enumerate(self.workloads):
            total = outbound[position]
            features.append([
                *(float(workload.template == name) for name in self.templates),
                log1p(inbound[position]),
                log1p(outbound[position]),
                denied[position] / total if total else 0.0,
                float(len(destinations[position])),
                float(len(ports[position])),
                float(workload.running),
                float(workload.quarantined),
            ])
        if message_edges:
            edge_index = torch.tensor(
                [[item[0] for item in message_edges], [item[1] for item in message_edges]],
                dtype=torch.long,
            )
            edge_weight = torch.tensor([item[2] for item in message_edges], dtype=torch.float32)
        else:
            edge_index = torch.empty((2, 0), dtype=torch.long)
            edge_weight = torch.empty((0,), dtype=torch.float32)
        return torch.tensor(features, dtype=torch.float32), edge_index, edge_weight

    def pairs(self, edges: set[tuple[str, str]]) -> Tensor:
        valid = sorted(
            (self.index[source], self.index[destination])
            for source, destination in edges
            if source in self.index and destination in self.index and source != destination
        )
        return torch.tensor(valid, dtype=torch.long).T.contiguous() if valid else torch.empty((2, 0), dtype=torch.long)

    def relation_features(
        self,
        snapshot: GraphSnapshot,
        edges: set[tuple[str, str]],
    ) -> Tensor:
        observed = {
            (edge.source_id, edge.destination_id): edge for edge in snapshot.edges
        }
        descriptors = {item.id: item for item in self.workloads}
        rows: list[list[float]] = []
        for source, destination in sorted(
            edge for edge in edges
            if edge[0] in self.index and edge[1] in self.index and edge[0] != edge[1]
        ):
            edge = observed.get((source, destination))
            total = edge.flow_count if edge else 0
            denied_ratio = edge.denied_count / total if total else 0.0
            same_tenant = descriptors[source].tenant_id == descriptors[destination].tenant_id
            rows.append([
                float(same_tenant),
                float((source, destination) in self.approved_edges),
                denied_ratio,
                float(not same_tenant),
            ])
        return (
            torch.tensor(rows, dtype=torch.float32)
            if rows
            else torch.empty((0, len(RELATION_FEATURE_NAMES)), dtype=torch.float32)
        )

    def edge_set(self, snapshot: GraphSnapshot) -> set[tuple[str, str]]:
        return {
            (edge.source_id, edge.destination_id)
            for edge in snapshot.edges
            if edge.source_id in self.index and edge.destination_id in self.index
        }

    def negative_edges(self, positives: set[tuple[str, str]], rng: random.Random) -> set[tuple[str, str]]:
        candidates = [
            (source.id, destination.id)
            for source in self.workloads
            for destination in self.workloads
            if source.id != destination.id and (source.id, destination.id) not in positives
        ]
        rng.shuffle(candidates)
        return set(candidates[: max(1, len(positives))])


class TemporalGraphEngine:
    def __init__(
        self,
        workloads: list[WorkloadDescriptor],
        hidden_channels: int = 16,
        *,
        seed: int = 0,
        approved_edges: set[tuple[str, str]] | None = None,
    ):
        torch.manual_seed(seed)
        self.tensorizer = GraphTensorizer(workloads, approved_edges)
        self.model = TemporalLinkPredictor(len(self.tensorizer.feature_names), hidden_channels)
        self.threshold: float | None = None

    @classmethod
    def from_checkpoint(
        cls,
        path: Path,
        workloads: list[WorkloadDescriptor],
        *,
        approved_edges: set[tuple[str, str]] | None = None,
        maximum_bytes: int = 10 * 1024 * 1024,
    ) -> "TemporalGraphEngine":
        """Load a local weights-only checkpoint after validating its schema."""
        if path.is_symlink():
            raise ValueError("Temporal model must be a regular .pt file")
        path = path.resolve(strict=True)
        if path.suffix.lower() != ".pt":
            raise ValueError("Temporal model must be a regular .pt file")
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            raise ValueError("Temporal model file is invalid or too large")
        try:
            checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        except (OSError, RuntimeError, EOFError, pickle.UnpicklingError) as exc:
            raise ValueError("Temporal model checkpoint cannot be loaded safely") from exc
        if not isinstance(checkpoint, dict) or set(checkpoint) != {"state_dict", "artifact"}:
            raise ValueError("Temporal model checkpoint has an invalid schema")
        state = checkpoint["state_dict"]
        artifact = checkpoint["artifact"]
        if not isinstance(state, dict) or not isinstance(artifact, dict):
            raise ValueError("Temporal model checkpoint has invalid contents")
        if artifact.get("model_version") != MODEL_VERSION:
            raise ValueError("Temporal model version is not supported")
        training = artifact.get("training")
        feature_names = artifact.get("feature_names")
        if (
            not isinstance(training, dict)
            or not isinstance(feature_names, list)
            or not all(isinstance(name, str) for name in feature_names)
        ):
            raise ValueError("Temporal model metadata is incomplete")
        threshold = training.get("threshold")
        if not isinstance(threshold, (int, float)) or not 0.0 <= float(threshold) <= 1.0:
            raise ValueError("Temporal model threshold is invalid")
        decoder_weight = state.get("decoder.0.weight")
        if not isinstance(decoder_weight, Tensor) or decoder_weight.ndim != 2:
            raise ValueError("Temporal model dimensions are invalid")
        hidden_channels = int(decoder_weight.shape[0])
        engine = cls(
            workloads,
            hidden_channels=hidden_channels,
            seed=0,
            approved_edges=approved_edges,
        )
        if feature_names != list(engine.tensorizer.feature_names):
            raise ValueError("Temporal model feature schema does not match the active lab")
        if artifact.get("relation_feature_names") != list(RELATION_FEATURE_NAMES):
            raise ValueError("Temporal model relationship schema does not match the active lab")
        try:
            engine.model.load_state_dict(state, strict=True)
        except (RuntimeError, TypeError) as exc:
            raise ValueError("Temporal model weights are incompatible") from exc
        engine.threshold = float(threshold)
        engine.model.eval()
        return engine

    def fit(self, snapshots: list[GraphSnapshot], *, seed: int, epochs: int = 80) -> TemporalTrainingResult:
        if len(snapshots) < 10:
            raise ValueError("At least ten chronological benign snapshots are required")
        ordered = sorted(snapshots, key=lambda item: item.window_start)
        if len({item.window_start for item in ordered}) != len(ordered):
            raise ValueError("Snapshot times must be unique")
        train_end = int(len(ordered) * 0.6)
        calibration_end = int(len(ordered) * 0.8)
        training = ordered[:train_end]
        calibration = ordered[train_end:calibration_end]
        testing = ordered[calibration_end:]
        torch.manual_seed(seed)
        random.seed(seed)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.01, weight_decay=1e-4)
        started = perf_counter()
        final_loss = 0.0
        self.model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            hidden = None
            losses = []
            rng = random.Random(f"{seed}:{epoch}")
            for current, following in zip(training, training[1:]):
                x, edge_index, edge_weight = self.tensorizer.tensors(current)
                hidden = self.model.encode(x, edge_index, edge_weight, hidden)
                positives = self.tensorizer.edge_set(following)
                negatives = self.tensorizer.negative_edges(positives, rng)
                positive_pairs = self.tensorizer.pairs(positives)
                negative_pairs = self.tensorizer.pairs(negatives)
                pairs = torch.cat((positive_pairs, negative_pairs), dim=1)
                relations = torch.cat((
                    self.tensorizer.relation_features(following, positives),
                    self.tensorizer.relation_features(following, negatives),
                ))
                labels = torch.cat((torch.ones(positive_pairs.shape[1]), torch.zeros(negative_pairs.shape[1])))
                losses.append(F.binary_cross_entropy_with_logits(self.model.decode(hidden, pairs, relations), labels))
            loss = torch.stack(losses).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 5.0)
            optimizer.step()
            final_loss = float(loss.detach())
        self.threshold = self._calibrate(training, calibration)
        return TemporalTrainingResult(
            self.threshold,
            len(training),
            len(calibration),
            len(testing),
            epochs,
            final_loss,
            (perf_counter() - started) * 1_000,
            seed,
        )

    def _calibrate(self, training: list[GraphSnapshot], calibration: list[GraphSnapshot]) -> float:
        self.model.eval()
        hidden = None
        anomalies: list[float] = []
        with torch.no_grad():
            for snapshot in training:
                x, edge_index, edge_weight = self.tensorizer.tensors(snapshot)
                hidden = self.model.encode(x, edge_index, edge_weight, hidden)
            for snapshot in calibration:
                pairs = self.tensorizer.pairs(self.tensorizer.edge_set(snapshot))
                if pairs.shape[1]:
                    relations = self.tensorizer.relation_features(snapshot, self.tensorizer.edge_set(snapshot))
                    probabilities = torch.sigmoid(self.model.decode(hidden, pairs, relations))
                    anomalies.extend(float(1 - value) for value in probabilities)
                x, edge_index, edge_weight = self.tensorizer.tensors(snapshot)
                hidden = self.model.encode(x, edge_index, edge_weight, hidden)
        if not anomalies:
            raise ValueError("Calibration windows contain no observed edges")
        ordered = sorted(anomalies)
        index = min(len(ordered) - 1, int(0.95 * len(ordered)))
        return max(0.5, min(0.99, ordered[index]))

    def prime(self, snapshots: list[GraphSnapshot]) -> Tensor:
        self.model.eval()
        hidden = None
        with torch.no_grad():
            for snapshot in sorted(snapshots, key=lambda item: item.window_start):
                x, edge_index, edge_weight = self.tensorizer.tensors(snapshot)
                hidden = self.model.encode(x, edge_index, edge_weight, hidden)
        if hidden is None:
            raise ValueError("At least one snapshot is required")
        return hidden

    def score(self, snapshot: GraphSnapshot, hidden: Tensor) -> tuple[tuple[TemporalEdgeScore, ...], Tensor]:
        if self.threshold is None:
            raise RuntimeError("Fit and calibrate the temporal model before scoring")
        edges = sorted(self.tensorizer.edge_set(snapshot))
        pairs = self.tensorizer.pairs(set(edges))
        self.model.eval()
        with torch.no_grad():
            relations = self.tensorizer.relation_features(snapshot, set(edges))
            probabilities = torch.sigmoid(self.model.decode(hidden, pairs, relations)) if edges else torch.empty(0)
            x, edge_index, edge_weight = self.tensorizer.tensors(snapshot)
            next_hidden = self.model.encode(x, edge_index, edge_weight, hidden)
        scores = []
        for position, ((source, destination), probability) in enumerate(
            zip(edges, probabilities)
        ):
            learned_novelty = 1.0 - float(probability)
            approved = float(relations[position, 1])
            denied_ratio = float(relations[position, 2])
            cross_tenant = float(relations[position, 3])
            # Relational facts do not replace the learned score. They bound the
            # risk floor so a novel denied/tenant-crossing edge cannot be hidden
            # by a confident link prediction.
            anomaly = max(
                learned_novelty,
                0.85 * denied_ratio,
                0.90 * cross_tenant * (1.0 - approved),
            )
            scores.append(TemporalEdgeScore(
                source,
                destination,
                float(probability),
                anomaly,
                anomaly >= self.threshold,
            ))
        return tuple(scores), next_hidden

    def artifact(self, result: TemporalTrainingResult) -> dict:
        return {
            "model_version": MODEL_VERSION,
            "feature_names": list(self.tensorizer.feature_names),
            "relation_feature_names": list(self.tensorizer.relation_feature_names),
            "training_node_count": len(self.tensorizer.workloads),
            "training": asdict(result),
        }
