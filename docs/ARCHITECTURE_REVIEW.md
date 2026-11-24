# Architecture review — 21 November 2026

## Decision

Retain a React portal and one FastAPI modular monolith. Treat Kubernetes/Cilium/Hubble as infrastructure adapters and the temporal-graph detector as the single advanced detector. Do not add control-plane microservices for the FYP.

## Rationale

The demonstrator has two connected workflows: bounded self-service workload lifecycle and zero-trust detection/containment. One API preserves authorization, audit and operation consistency while logical modules separate management-plane and security-plane responsibilities. Kubernetes remains internal; users select allowlisted templates rather than submitting manifests.

## Accepted trade-offs

- SQLite and a local K3s lab reduce deployment complexity but do not demonstrate public-cloud scale or high availability.
- A 30-second graph window makes experiments reproducible but limits detection-time resolution.
- Correlating learned risk with explicit policy facts reduces unsafe automatic response, but it means the evaluated system is a risk engine rather than a pure link predictor.
- The temporal model improves aggregate recall and catches the vertical-port-scan case, but has worse false-positive rate and average precision than the frequency baseline.

## Validation plan

- Preserve the existing 12-scenario, five-seed, 30-repetition offline evaluation.
- Verify authentication, tenant authorization, idempotent lifecycle operations and incident transitions through automated tests.
- Verify default-deny, approved paths and quarantine against positive and negative controls in the K3s/Cilium lab.
- Measure live containment time, restore time and CPU/memory/network overhead before making performance claims.

## Review findings

The current architecture is appropriate for an FYP and should not be split further. The main evidence gap is live-system measurement, not another component. The report and IEEE-style manuscript must describe offline metrics as offline metrics and list containment/recovery/overhead as future evaluation work.
