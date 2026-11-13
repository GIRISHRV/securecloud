# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation

## 1. Problem Statement

Organizations host applications belonging to different departments or customers on shared cloud infrastructure. When an application is compromised, an attacker can attempt lateral movement toward other services, databases, and tenant resources. Static access policies restrict communication, while changing workload behaviour requires continuous monitoring and timely response. Administrators need a unified platform for managing workloads, identifying suspicious activity, and containing affected resources while maintaining service availability.

## 2. Abstract

SecureCloud proposes a self-service multi-tenant private-cloud platform with an integrated zero-trust security plane. Users manage tenants and deploy approved web, API, and database workloads through a cloud-style portal. Kubernetes provides workload orchestration, while tenant-aware policies enforce default-deny communication. The proposed detection pipeline combines sliding-window behavioural rules, learned anomaly scoring, and an experimental temporal graph model to identify suspicious communication patterns. Risk assessment drives predefined containment actions, and administrators inspect incident evidence and authorize recovery. The platform will be evaluated using prevention rate, detection rate, false-positive rate, containment time, service disruption, and resource overhead in a two-tenant laboratory deployment.

## 3. Existing Limitations

- Static policies require maintenance as applications and their communication requirements change.
- Fixed event-count thresholds can miss low-rate attacks and flag legitimate traffic surges.
- Individual connection alerts provide limited context about behaviour across services and time.
- Delayed containment allows a compromised workload to continue using previously approved connections.
- Broad quarantine can interrupt services that depend on the affected workload.
- Recovery requires coordination between investigation, application repair, data restoration, and access approval.

## 4. What We Are Solving

- Provide tenant-authorized deployment, inspection, stopping, and deletion through one portal.
- Enforce approved workload communication and isolate tenant resources.
- Combine recent activity, learned behaviour, and communication relationships to identify suspicious patterns.
- Restrict suspicious paths or quarantine compromised workloads through predefined response actions.
- Preserve incident evidence and maintain quarantine across workload replacement.
- Support trusted rebuilds, verified data recovery, health checks, and authorized reconnection.
- Measure protection, false alarms, response speed, and impact on dependent and unrelated services.

The portal starts empty and provides an explicit Load demo action for College/Hospital samples. It supports arbitrary tenant records; the infrastructure demonstrator provisions two tenants using three approved workload templates.

## 5. Algorithms Proposed

| Algorithm / method | Input | Processing | Output |
| --- | --- | --- | --- |
| Tenant-aware policy evaluation | Workload identity, tenant, destination, approved paths, quarantine state | Match requests against default-deny access rules | Allow or deny decision |
| Sliding-window behavioural detection | Recent connection events and explicit verdicts | Calculate denied-attempt counts, cross-tenant attempts, destination diversity, and port/service fan-out | Explainable suspicious-activity indicators |
| Half-Space Trees anomaly detection | Aggregated workload behaviour features | Train on reviewed benign observations and calibrate a threshold on separate benign data | Workload anomaly score |
| Temporal graph link prediction — experimental | Time-stamped workload communication graphs | Encode graph structure with a GNN and temporal changes with a sequence model; score unusual relationships | Edge anomaly scores and workload risk evidence |
| Temporal risk aggregation | Recent anomaly scores, rule indicators, and policy context | Smooth recent scores and evaluate sustained elevation with supporting evidence against calibrated action thresholds | Review, selective restriction, or quarantine recommendation |
| Containment and recovery state machine | Incident evidence, authorization, workload state, verification results | Apply an approved playbook; verify containment; track investigation, recovery, and release | Auditable response history and restored approved access |

Training, calibration, and evaluation use chronological data splits. Rule-only, edge-frequency, and Half-Space Trees baselines will be compared with temporal graph scoring. Risk thresholds and response conditions will be fixed before final evaluation.

## 6. Architecture and Tech Stack

```text
Application owner / Security administrator
                    |
          React + Fluent UI portal
                    |
       Tenant-authorized FastAPI backend
          /                       \
 Management plane             Security plane
 Tenants and catalog          Identity and policy
 Lifecycle and quotas         Telemetry and detection
 Operations and health        Containment and evidence
          \                       /
            Kubernetes adapter
                    |
      Kubernetes + Cilium workload lab
```

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Portal | React, TypeScript, Vite, Microsoft Fluent UI | Tenant, catalog, workload, topology, and incident workflows |
| API | Python, FastAPI, Argon2, session authentication | Tenant authorization, validation, lifecycle requests, and audit records |
| Persistence | SQLite | Users, memberships, workloads, operations, and audit records |
| Orchestration | Kubernetes — planned integration | Namespaces, bounded workload templates, lifecycle, and reconciliation |
| Network security | Cilium / Kubernetes policies — planned integration | Default-deny communication and containment |
| Telemetry | Hubble, Tetragon, Kubernetes audit logs — proposed | Network flows, runtime activity, and API events |
| Behaviour analysis | River Half-Space Trees | Feature-based anomaly detection |
| Graph research | PyTorch / PyTorch Geometric — proposed | Temporal graph model training and inference |
| Verification | Pytest, Vitest, Playwright, controlled traffic tests | API, detector, portal, and enforcement validation |

The backend follows a modular monolith structure. Stable tenant and workload identities link telemetry, policies, and incident evidence. Selective restrictions and full quarantine use authorized playbooks. Recovery follows investigation, trusted rebuild or verified data restoration, health verification, and approved reconnection. Optional forensic checkpointing supports investigation alongside prompt containment.

## 7. Literature Study

| No. | Author / organization | Year | Title | Method / contribution | Relevance to SecureCloud |
| --- | --- | --- | --- | --- | --- |
| 1 | Rose et al., NIST | 2020 | [Zero Trust Architecture, SP 800-207](https://www.nist.gov/publications/zero-trust-architecture) | Policy-based access decisions and enforcement | Foundation for workload authorization and least-privilege access |
| 2 | Chandramouli and Butcher, NIST | 2023 | [A Zero Trust Architecture Model for Access Control in Cloud-Native Applications in Multi-Cloud Environments, SP 800-207A](https://csrc.nist.gov/pubs/sp/800/207/a/final) | Identity-aware application and service access control | Cloud-native security-plane design |
| 3 | King and Huang | 2023 | [Euler: Detecting Network Lateral Movement via Scalable Temporal Link Prediction](https://isaiahjking.com/papers/EulerACM.pdf) | Graph neural networks and sequence encoding for anomalous link detection | Temporal graph detection experiment |
| 4 | River project | Living documentation | [Half-Space Trees](https://riverml.xyz/latest/api/anomaly/HalfSpaceTrees/) | Feature-based anomaly scoring with documented scaling requirements | Lightweight learned detection baseline |
| 5 | Kubernetes project | Living documentation | [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/) | Workload ingress and egress controls | Tenant isolation and approved communication paths |
| 6 | Cilium project | Living documentation | [Deny Policies](https://docs.cilium.io/en/latest/security/policy/deny/) | Explicit deny rules with precedence over allow rules | Selective restrictions and workload quarantine |
| 7 | Kubernetes project | Living documentation | [Kubelet Checkpoint API](https://kubernetes.io/docs/reference/node/kubelet-checkpoint-api/) | Runtime-dependent capture of container execution state | Optional forensic evidence collection |
