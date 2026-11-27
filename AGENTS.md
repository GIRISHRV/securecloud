# SecureCloud Project Guidance for Agents

## Project

**Official title:** SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation

Build a self-service multi-tenant private-cloud prototype with an integrated zero-trust security plane. It is Azure-like only at the portal-workflow level: users create projects, deploy catalog workloads, manage lifecycle and network intent, and inspect health. Kubernetes supplies orchestration; the project does not implement a hypervisor, storage fabric, billing system, or public-cloud scale.

The target demonstrator is a multi-shop mall: two fixed testbed shops (Northstar, Bloom) plus merchant shops provisioned on demand from one allowlisted shop template, each its own tenant with containerized resources. The security workflow enforces default-deny communication, detects suspicious behaviour, quarantines an affected workload, and exposes authorized web incident controls. Mobile is deferred. Use `docs/IMPLEMENTATION_PLAN.md` for the active scope and verify implementation claims against code and test evidence.

## Architecture Rules

- Read `docs/IMPLEMENTATION_PLAN.md` before continuing. Distinguish implemented behaviour from planned work using code and test evidence.
- Keep project documentation under docs and college/review materials under collegedocs, except this root AGENTS.md. Do not move vendor documentation in node_modules.
- The single-node lab runs at most five live shops (`SECURECLOUD_SHOP_QUOTA`, default 5, counting the two testbed shops); the quota is enforced server-side, and the UI explains it instead of failing. The portal UI supports arbitrary tenants. The attack testbed (`/lab`) stays on the fixed Northstar/Bloom/ShipFast topology so results are repeatable. Keep three workload templates and deploy/inspect/stop/delete. Mobile, extensive lifecycle controls, and publication commitments are deferred.
- Require authenticated tenant authorization before adding portal mutations. The loopback observer is not the production API.
- Never infer enforcement from a timeout, policy existence, or readiness. Retain unknown/inconclusive states and record positive controls.
- Use identical static policies as the evaluation baseline. Demonstrate withdrawal of a compromised source's previously allowed access and measure disruption.
- Quarantine must survive reconciliation and pod replacement. Do not promise unaffected dependent applications.
- Treat existing literature summaries as unverified until primary sources are read. Do not claim novelty from the feature combination alone.

- Prefer a modular monolith API for the FYP; do not split the control plane into unnecessary microservices.
- Treat Kubernetes as an internal infrastructure adapter. Portal users submit safe catalog requests, never raw Kubernetes YAML.
- Separate the cloud management plane (tenant, catalog, deployment, lifecycle, quota, operation and topology) from the security plane (identity, policy, telemetry, detection, containment and evidence).
- Provision only allowlisted workload templates with bounded CPU and memory; do not create a general-purpose arbitrary-container hosting service.
- Keep stop/delete tenant-authorized, idempotent and serialized per deployment. Require exact-name confirmation; use Kubernetes UID/version preconditions and verify completion. Never force-delete or clear security labels to make lifecycle operations pass.
- Use Kubernetes namespaces, workload labels, Kubernetes/Cilium network policies, and least-privilege RBAC to model tenant isolation.
- Use the temporal-graph link-prediction engine as the single advanced detector. Correlate its score with explicit facts such as policy denials, cross-tenant attempts, and scanning behaviour; keep a simple edge-frequency scorer as the evaluation baseline.
- The framework's value is runtime enforcement and containment. Logs and dashboards support that value; they are not the product by themselves.
- State limitations honestly: containers simulate virtualized workloads and the project does not replace cloud-provider tenant isolation.

## Required Skills by Task

| Task | Skill(s) to use | Expected outcome |
|---|---|---|
| Architecture, HLD, trade-offs, or ADRs | `architecture`, then `architect-review` | Document the decision, alternatives, rationale, accepted trade-offs, and validation plan. |
| Literature survey or research-gap analysis | `deep-research` when a configured API key/budget is available; otherwise use authoritative academic/official web research | Cite recent, relevant primary sources and distinguish evidence from project claims. |
| Kubernetes tenant isolation or policy enforcement | `k8s-security-policies` | Default-deny policies, namespace isolation, least-privilege RBAC, restricted pod security, and verification steps. |
| Docker/Kubernetes deployment | `kubernetes-deployment` | Container build, manifests, security configuration, observability, deployment, and rollback/verification plan. |
| Container image/runtime hardening | `container-security-hardening` | Non-root workloads, read-only filesystem where possible, dropped capabilities, resource limits, image scans, and no embedded secrets. |
| Web UI implementation | `frontend-architecture`, `react-best-practices` | Maintainable role-based cloud portal with provisioning, catalog, topology, incident, and policy workflows. |
| Mobile implementation | `react-native-architecture`, `mobile-developer` | Secure mobile alert, approval, quarantine, and restore workflows. |
| Application/API security | `api-security-best-practices`, `backend-security-coder` | Tenant-scoped authorization on every API operation, secure token handling, input validation, and audit events. |
| Formal architecture documentation after code exists | `c4-architecture-c4-architecture` | C4 context, container, component, and deployment documentation based on the implementation. |
| Review presentation | `2slides-ppt-generator` only when the user supplies/configures its API key and approves credit use | Create a review deck from approved, fact-checked documentation. |

## Review Quality Bar

- Every review document must use the full official project title.
- Explain the problem as post-compromise lateral movement in organization-managed multi-tenant workloads; never claim that public cloud providers casually expose one customer's infrastructure to another.
- Every proposed feature must map to one of two connected demonstrable flows: self-service tenant/workload lifecycle, or policy enforcement/detection/quarantine/restore.
- Never say the project builds Azure from scratch. Say it builds an Azure-like self-service private-cloud prototype on Kubernetes.
- Include measurable evaluation criteria: prevention rate, detection rate, false-positive rate, containment time, and policy/network overhead.
- Before a review, use `architect-review` to identify unnecessary complexity, unsupported claims, and untested assumptions.

## Safety and Scope

- Use only isolated, project-owned labs and synthetic attack traffic.
- Do not run scans, containment actions, or other tests against external systems.
- Do not hard-code tokens, passwords, keys, or service credentials in source or documentation.

## Kokonut UI

This project installs components from Kokonut UI, a shadcn/ui registry.
The registry is set in `frontend/components.json` as `@kokonutui`.

- Before building an animated or interactive component from scratch, check https://kokonutui.com/llms.txt.
- Install components from `frontend` with `npx shadcn@latest add @kokonutui/<name>`; do not paste registry source manually.
- Installed components are project code. Edit them in place instead of wrapping them.
