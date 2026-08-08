# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation

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
