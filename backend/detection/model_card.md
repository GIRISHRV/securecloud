# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation — Temporal Graph Model Card

## Model

- Version: `gconvgru-link-v2`
- Task: predict directed workload edges in the next 30-second graph snapshot.
- Encoder: Chebyshev graph-convolutional GRU with symmetric Laplacian normalization.
- Decoder: directed multilayer link decoder using source, destination, and relationship features.
- Incident condition: calibrated anomaly threshold exceeded and at least one explicit fact is present: cross-tenant communication, policy denial, horizontal fan-out, or vertical port fan-out.

The cell follows the MIT-licensed PyTorch Geometric Temporal `GConvGRU` equations and API using base PyTorch Geometric `ChebConv`. The compatibility implementation is required because release `0.56.2` imports unrelated `torch-sparse` models from its package initializer, while no matching Python 3.14 Windows `torch-sparse` wheel was available during implementation. Attribution is preserved in `THIRD_PARTY_NOTICES.md`.

## Inputs

Stable workload IDs form graph nodes. Tenant names and IDs are excluded from learned features. Node features are template one-hot values, inbound and outbound log-counts, denied-flow ratio, unique destination and port counts, running state, and quarantine state. Relationship features encode same-tenant status, approved intent, policy-denied ratio, and cross-tenant status.

## Training and calibration

- Training data: reviewed benign service traffic including the explicit vendor-to-retail maintenance relationship.
- Split: chronological 60% training, 20% calibration, 20% held-out test.
- Negative sampling: one absent directed edge per positive edge for every next-window training target.
- Optimizer: Adam, learning rate `0.01`, weight decay `0.0001`.
- Epochs: 80.
- Seeds: 11, 29, 47, 71, and 101.
- Calibration: 95th percentile of benign calibration anomaly scores, bounded to `[0.5, 0.99]`.

No future benchmark window is used to update model weights. Saved per-seed state dictionaries, feature schemas, thresholds, and metadata are written under `runtime/experiments/temporal-final/models/`. Seed 11 is packaged as the default local demonstration checkpoint.

## Current evaluation

The comparison uses 12 allowlisted scenarios, 30 repetitions, five seeds, identical static policies, and identical event sequences (1,800 scenario runs).

| Configuration | Precision | Recall | F1 | FPR | Average precision | Mean detection latency |
|---|---:|---:|---:|---:|---:|---:|
| Edge-frequency baseline | 1.000 | 0.846 | 0.917 | 0.000 | 0.880 | 28.0 s |
| Temporal-graph risk engine | 0.923 | 0.923 | 0.923 | 0.091 | 0.771 | 28.3 s |

The temporal engine detected the vertical port-scan scenario with 1.000 recall, while the edge-frequency baseline measured 0.000 recall. Mean GConvGRU training time was 7,212 ms per seed and mean scenario inference time was 8.10 ms. These are local offline measurements, not live cluster or cloud-scale performance results.

## Limitations

- The reviewed history and scenario topology are small and project-generated.
- A relational risk floor prevents a high learned link probability from hiding an explicit denied or unapproved cross-tenant edge; results therefore describe a temporal-graph risk engine, not a pure link predictor.
- The explicit-fact gate eliminates the benign new-deployment alert in this benchmark, so detector score quality must also be assessed using average precision.
- Recall improves over the baseline, but precision and average precision are lower and the false-positive rate is higher. Longer live histories and calibration remain necessary.
- Offline evaluation does not measure live containment, recovery time, or CPU/memory overhead.

## References

- PyTorch Geometric Temporal `GConvGRU` documentation: https://pytorch-geometric-temporal.readthedocs.io/en/stable/modules/root.html
- PyTorch Geometric Temporal paper: https://arxiv.org/abs/2104.07788
- Structured Sequence Modeling with Graph Convolutional Recurrent Networks: https://arxiv.org/abs/1612.07659
