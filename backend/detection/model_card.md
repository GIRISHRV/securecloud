# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation — Temporal Graph Model Card

## Model

- Version: `gconvgru-link-v1`
- Task: predict directed workload edges in the next 30-second graph snapshot.
- Encoder: Chebyshev graph-convolutional GRU with symmetric Laplacian normalization.
- Decoder: trainable directed bilinear link decoder.
- Incident condition: calibrated anomaly threshold exceeded and at least one explicit fact is present: cross-tenant communication, policy denial, horizontal fan-out, or vertical port fan-out.

The cell follows the MIT-licensed PyTorch Geometric Temporal `GConvGRU` equations and API using base PyTorch Geometric `ChebConv`. The compatibility implementation is required because release `0.56.2` imports unrelated `torch-sparse` models from its package initializer, while no matching Python 3.14 Windows `torch-sparse` wheel was available during implementation. Attribution is preserved in `THIRD_PARTY_NOTICES.md`.

## Inputs

Stable workload IDs form graph nodes. Features are template one-hot values, tenant one-hot values, inbound and outbound log-counts, denied-flow ratio, unique destination and port counts, running state, and quarantine state. Observed directed flows form edges; encoder message passing uses a symmetric view while the decoder remains directed.

## Training and calibration

- Training data: reviewed benign College/Hospital benchmark windows.
- Split: chronological 60% training, 20% calibration, 20% held-out test.
- Negative sampling: one absent directed edge per positive edge for every next-window training target.
- Optimizer: Adam, learning rate `0.01`, weight decay `0.0001`.
- Epochs: 80.
- Seeds: 11, 29, 47, 71, and 101.
- Calibration: 95th percentile of benign calibration anomaly scores, bounded to `[0.5, 0.99]`.

No future benchmark window is used to update model weights. Saved per-seed state dictionaries, feature schemas, thresholds, and metadata are written under `runtime/experiments/offline/models/`.

## Current evaluation

The comparison uses 11 allowlisted scenarios, 30 repetitions, five seeds, identical static policies, and identical event sequences.

| Configuration | Precision | Recall | F1 | FPR | Average precision | Mean detection latency |
|---|---:|---:|---:|---:|---:|---:|
| Edge-frequency baseline | 1.000 | 0.818 | 0.900 | 0.000 | 0.859 | 30.0 s |
| GConvGRU link predictor | 1.000 | 0.818 | 0.900 | 0.000 | 0.793 | 30.0 s |

Mean GConvGRU training time was 3149 ms per seed and mean scenario inference time was 3.70 ms on the development machine. These are local-lab measurements, not cloud-scale performance results.

## Limitations

- The current reviewed history contains only two tenants and a small fixed topology.
- Link prediction detects unusual edges; it does not independently identify malicious volume on a normal approved edge.
- The explicit-fact gate eliminates the benign new-deployment alert in this benchmark, so detector score quality must also be assessed using average precision.
- The learned model does not outperform the edge-frequency baseline on the current dataset. Its value must be reassessed after collecting longer, more varied live Hubble histories.
- Offline model inference is implemented and evaluated; loading the model into the continuous API telemetry loop remains pending.

## References

- PyTorch Geometric Temporal `GConvGRU` documentation: https://pytorch-geometric-temporal.readthedocs.io/en/stable/modules/root.html
- PyTorch Geometric Temporal paper: https://arxiv.org/abs/2104.07788
- Structured Sequence Modeling with Graph Convolutional Recurrent Networks: https://arxiv.org/abs/1612.07659
