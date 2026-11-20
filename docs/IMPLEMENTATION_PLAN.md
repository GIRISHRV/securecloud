# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation — MVP Implementation Plan

## 1. MVP Definition

SecureCloud has two codebases:

1. `frontend/` — the complete web interface.
2. `backend/` — API, persistence, Kubernetes control, zero-trust enforcement, telemetry, detection engine, experiments, and tests.

The MVP demonstrates one end-to-end scenario:

```text
Sign in
→ create or select a tenant
→ deploy an approved workload
→ observe its actual Kubernetes state
→ enforce approved network paths
→ collect Hubble flow records
→ detect an anomalous connection with the temporal-graph engine
→ create an incident
→ quarantine the source workload
→ verify containment
→ restore the approved policy
```

The infrastructure demonstrator supports two active lab tenants and three bounded template classes: web, API/worker, and database/cache. The frontend data model is not restricted to two tenants. The target reference lab is a generic retail organization and a facilities vendor, based on a bounded adaptation of Google Cloud's Apache-2.0 Online Boutique. The current School/Hospital three-tier applications remain an implemented compatibility fixture until the retail stack replaces them.

### 1.1 Demonstration narrative

The target demonstration is inspired by the publicly documented 2013 Target breach: stolen third-party vendor credentials were used for initial access, followed by movement toward sensitive retail systems and point-of-sale malware. Target's [written Senate testimony](https://www.commerce.senate.gov/wp-content/uploads/media/doc/Mulligan%20Testimony.pdf) supports the vendor-credential and point-of-sale facts; the Senate staff [kill-chain analysis](https://www.commerce.senate.gov/wp-content/uploads/media/doc/2014%200325%20Target%20Kill%20Chain%20Analysis.pdf) explicitly notes uncertainty about the exact escalation path. SecureCloud therefore does **not** claim to reproduce the historical attack. It recreates only the defensible security problem: a trusted vendor relationship is compromised and then used abnormally.

The end-to-end demonstration is:

```text
Create RetailCo and FacilitiesVendor tenants
→ deploy approved functional application stacks
→ establish one explicit vendor-to-maintenance business intent
→ generate ordinary shopping and maintenance activity
→ learn a tenant-agnostic benign communication baseline
→ use the valid vendor path in an abnormal temporal pattern
→ detect rising risk while requests are still policy-allowed
→ attempt a forbidden payment-service connection
→ show deterministic Cilium prevention
→ quarantine the compromised vendor workload
→ verify withdrawal of its previously allowed maintenance access
→ review, restore, and verify least-privilege access
```

This separates the two contributions visibly:

- The temporal model detects abnormal use of technically valid access.
- Static zero-trust policy prevents explicitly unauthorized access, and the response plane contains and restores the workload.

## 2. Repository Layout

```text
actualfyp/
├── frontend/                 # React web application
│   ├── src/
│   ├── public/
│   ├── reference-app/         # School/Hospital compatibility fixture during migration
│   ├── tests/
│   ├── package.json
│   └── vite.config.ts
├── backend/                  # Everything outside the web interface
│   ├── api/                  # HTTP routes and request models
│   ├── auth/                 # sessions, roles, tenant authorization
│   ├── cloud/                # tenants, catalog, workloads, operations
│   ├── infrastructure/       # Kubernetes and Cilium adapters
│   ├── telemetry/            # Hubble ingestion and normalization
│   ├── detection/            # graph builder, model, scoring, rules
│   ├── incidents/            # evidence, quarantine, restore
│   ├── experiments/          # scenarios, evaluation, plots
│   ├── reference_apps/       # Compatibility fixture plus SecureCloud-owned retail/vendor services
│   ├── manifests/            # lab and workload manifests
│   └── tests/
├── docs/
│   └── IMPLEMENTATION_PLAN.md
├── collegedocs/
├── AGENTS.md
└── .gitignore
```

Directories under `backend/` are created only when their implementation phase begins. No empty architecture scaffolding is required.

## 2.1 Off-the-shelf component decisions

| Component | Decision | Modification required |
|---|---|---|
| Kokonut UI | Use selected free source components | Restyle for a compact cloud console and remove decorative motion |
| shadcn/ui | Use primitives directly | Apply SecureCloud tokens and validation behaviour |
| TanStack Table | Use directly | Define typed tenant, workload, operation, and incident columns |
| React Flow | Use for topology | Add SecureCloud workload nodes, policy edges, verdict colours, and read-only interaction |
| FastAPI and SQLite | Retain existing implementation | Split the large API module as features are connected |
| Kubernetes Python client | Use directly | Add bounded template and reconciliation logic |
| Cilium NetworkPolicy | Use directly | Generate only the approved-path and quarantine policies required by the MVP |
| Hubble JSON exporter | Use directly | Add a small file-tail collector and SecureCloud identity normalization |
| PyTorch Geometric Temporal `GConvGRU` | Reuse as the model encoder | Add graph construction, negative sampling, link decoder, calibration, and evidence records |
| Euler repository | Do not import | Reuse the published temporal-link-prediction method and evaluate it in the SecureCloud lab |
| [Google Cloud Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) | Reuse a bounded subset under Apache-2.0 | Retain notices; adapt branding, manifests, resource limits, persistence, labels, and SecureCloud catalog metadata |
| OWASP Juice Shop | Do not use as the main demonstrator | Its intentionally vulnerable monolith emphasizes web exploitation rather than workload-graph behaviour and lateral movement |

---

## 3. Phase One — UI/UX

### 3.1 UI stack

Use:

- React, TypeScript, and Vite.
- Tailwind CSS v4.
- shadcn/ui primitives.
- Kokonut UI source components.
- TanStack Table for resource tables.
- React Flow for the network map.
- Lucide icons.
- Motion only for short state transitions.

Kokonut UI is a shadcn registry whose components are copied into the repository and can be edited locally. Its setup requires Tailwind CSS v4 and the shadcn utility layer. See [Kokonut UI installation](https://kokonutui.com/docs).

TanStack Table supplies sorting, filtering, selection, and pagination without imposing a visual style. See [TanStack Table](https://tanstack.com/table/latest/docs/overview).

React Flow provides the node-and-edge canvas for the workload topology and is MIT licensed. See [React Flow](https://reactflow.dev/).

### 3.2 Screens

The MVP has exactly these screens:

1. **Login**
2. **Overview**
3. **Tenants and Workloads**
4. **Catalog**
5. **Network Map**
6. **Incidents**
7. **Workload details drawer**
8. **Incident details drawer**

There is no landing page, pricing page, marketing content, onboarding carousel, billing system, profile editor, theme marketplace, or mobile application.

### 3.3 Console shell

Build a compact cloud-console layout:

- Permanent desktop sidebar.
- Drawer navigation on narrow screens.
- Page title and contextual action bar.
- Tenant selector.
- Account menu.
- Dense tables for resources and incidents.
- Drawers for details instead of separate deep page hierarchies.
- Toasts for completed actions.
- Inline alerts for failed or inconclusive operations.
- Empty states with one primary action.

Use Kokonut UI only where it reduces implementation work:

| Need | Component |
|---|---|
| Mobile navigation | Smooth Drawer |
| Account controls | Account Menu |
| Async operation result | Promise Toast |
| API or policy warning | Inline Alert |
| Empty tenant/workload list | Empty State |
| Compact operation progress | Status Island |
| Workload/incident details | Stack Panel |

Tables, forms, tabs, dialogs, and confirmation controls use shadcn primitives styled to match the console. Decorative backgrounds, novelty buttons, animated cards, and AI-chat components are excluded.

### 3.4 UI data boundary

The frontend calls a typed `PortalService` interface. Provide two implementations:

- `ApiPortalService` for the real backend.
- `DemoPortalService` for the explicit Load demo mode.

The demo service is never used as evidence of Kubernetes deployment or network enforcement.

### 3.5 UI implementation order

1. Add Tailwind, shadcn, and the Kokonut registry.
2. Create tokens for colour, spacing, typography, status, and focus.
3. Replace the current Fluent shell with the console shell.
4. Implement Login.
5. Implement Tenants and Workloads with TanStack Table.
6. Implement Catalog deployment form.
7. Implement workload details and lifecycle confirmations.
8. Implement Network Map with React Flow.
9. Implement Incidents and incident details.
10. Connect all screens to `ApiPortalService`.
11. Retain Load demo as an explicit secondary action.

### 3.6 UI acceptance criteria

- All controls work with a keyboard.
- Focus is visible.
- Tables remain usable at 390 px width.
- No horizontal page overflow.
- Loading, empty, failed, inconclusive, and successful states are distinct.
- Tenant-scoped actions disappear or disable according to the authenticated role.
- No screen claims that a queued request is a completed infrastructure operation.

---

## 4. Phase Two — Temporal-Graph Detection Engine

### 4.1 Selected engine

Implement one advanced detector: **temporal graph link prediction**.

The engine learns normal workload-to-workload communication from benign graph snapshots and assigns a low likelihood to unexpected future edges. This follows the method demonstrated by King and Huang in [Euler: Detecting Network Lateral Movement via Scalable Temporal Graph Link Prediction](https://doi.org/10.14722/ndss.2022.24107).

Use the MIT-licensed PyTorch Geometric Temporal `GConvGRU` design rather than importing the full Euler research codebase. Release `0.56.2` cannot be imported normally in the Python 3.14 Windows lab because its package initializer requires an unavailable `torch-sparse` build, so the project retains an attributed API-compatible cell built on base PyTorch Geometric `ChebConv`. See the [project repository](https://github.com/benedekrozemberczki/pytorch_geometric_temporal), [`GConvGRU` documentation](https://pytorch-geometric-temporal.readthedocs.io/en/stable/modules/root.html), and `backend/detection/THIRD_PARTY_NOTICES.md`.

### 4.2 Graph definition

Create one directed graph snapshot every 30 seconds.

**Nodes:** stable SecureCloud workload IDs, not pod IP addresses.

**Node features:**

- Template type: web, API, or database.
- Inbound flow count.
- Outbound flow count.
- Denied-flow ratio.
- Unique destination count.
- Unique destination-port count.
- Workload running/quarantined state.
- Service role and exposure class from allowlisted catalog metadata.

Tenant names and tenant IDs are excluded from learned features. Stable IDs are used only for graph indexing and evidence. This allows one feature schema to score arbitrary tenant names and prevents a checkpoint from being coupled to `college`, `hospital`, `retail`, or `vendor` labels.

**Edges:** observed source-to-destination communication.

**Edge features:**

- Flow count.
- Allowed count.
- Denied count.
- Destination port.
- Protocol.
- Approved-path indicator.
- Cross-tenant indicator.
- Same-tenant indicator.
- Business-intent type, encoded from a bounded vocabulary rather than a tenant name.

### 4.3 Model

```text
30-second graph snapshots
        ↓
GConvGRU encoder
        ↓
node embeddings
        ↓
bilinear link decoder
        ↓
probability of an edge in the next snapshot
        ↓
anomaly score = 1 - predicted probability
```

Use negative sampling during training. Train only on reviewed benign windows. Split data chronologically into training, calibration, and held-out test sets.

### 4.4 Risk and incident decision

Score every resolved Hubble flow window, including policy-allowed traffic. Do not pre-filter the model input to denied or cross-tenant events. The graph anomaly score is the main learned signal. An exponentially weighted risk value carries evidence across consecutive windows without introducing a second learned detector:

```text
risk(t) = alpha × anomaly(t) + (1 - alpha) × risk(t-1)
```

Select `alpha`, the calibrated anomaly threshold, and the persistence threshold using calibration data only. Record both raw anomaly and accumulated risk. Explicit facts accompany the learned score:

- Cross-tenant attempt.
- Policy-denied verdict.
- Horizontal destination fan-out.
- Vertical port fan-out.
- Use of an approved cross-tenant intent outside its declared maintenance window.
- Workload lifecycle or identity change near the event.

The MVP incident rule is:

```text
Create an alert when:
  calibrated graph anomaly or accumulated-risk threshold is exceeded

Recommend automated containment only when:
  elevated learned risk persists
  AND at least one independently observed security fact is present
```

An ML-only alert remains reviewable evidence and is never represented as a confirmed attack. The detector does not write Cilium policies. It creates evidence and, when the stricter gate is met, a containment recommendation. The authorized middleware operation applies or restores policy.

### 4.5 Engine artifacts

```text
backend/detection/
├── schema.py             # normalized flow and snapshot models
├── windows.py            # event-time windows
├── graph.py              # graph snapshot construction
├── model.py              # GConvGRU and link decoder
├── train.py              # chronological training
├── calibrate.py          # threshold selection
├── infer.py              # online scoring
├── risk.py               # evidence correlation
└── model_card.md         # data, features, limits, metrics
```

Model outputs:

```text
backend/models/
├── temporal_graph.pt
├── feature_schema.json
├── calibration.json
└── metadata.json
```

### 4.6 Engine implementation order

1. Define normalized Hubble flow and graph-snapshot schemas.
2. Implement deterministic 30-second aggregation.
3. Implement stable workload identity resolution.
4. Implement graph construction and negative sampling.
5. Implement a simple edge-frequency baseline.
6. Implement `GConvGRU` plus the link decoder.
7. Implement chronological train/calibrate/test splits.
8. Implement offline evaluation.
9. Implement persisted model metadata and thresholds.
10. Add online inference to the backend process.
11. Create incidents from correlated evidence.

### 4.7 Engine acceptance criteria

- The same input event sequence creates the same graph snapshots.
- Training data cannot overlap calibration or test time ranges.
- A model cannot score data with a mismatched feature schema.
- Unknown telemetry identity produces an inconclusive result.
- Every incident records model version, threshold, score, supporting facts, and source events.
- The temporal model is compared with the edge-frequency baseline using the same held-out data.
- The same trained feature schema accepts arbitrary tenant names.
- Allowed and denied traffic are both scored.
- At least one held-out scenario can be detected before its first policy-denied event, or the project must report that no predictive lead time was demonstrated.

---

## 5. Phase Three — Cloud Management Backend

Retain FastAPI and SQLite for the MVP. The existing authenticated API and persisted operations are the starting point.

### 5.1 Complete the management API

1. Split the current API module by auth, tenant, workload, operation, and incident concerns.
2. Add a local bootstrap command for the first administrator.
3. Connect the frontend session flow.
4. Complete tenant membership management.
5. Add workload detail and health endpoints.
6. Add incident list/detail endpoints.
7. Add quarantine and restore endpoints.
8. Keep all mutations tenant-authorized, audited, idempotent, and input-validated.

### 5.2 Operation model

Infrastructure mutations use persisted operations:

```text
queued → running → succeeded
                 → failed
                 → inconclusive
```

The API returns desired state and observed state separately.

---

## 6. Phase Four — Kubernetes and Zero-Trust Enforcement

### 6.1 Reusable components

- Use the [official Kubernetes Python client](https://github.com/kubernetes-client/python) for namespaces, workloads, Services, and observed state.
- Use Kubernetes NetworkPolicy and CiliumNetworkPolicy for default deny, approved paths, selective denial, and quarantine.
- Use Hubble as the network-flow source.

### 6.2 Bounded templates

Implement three internal templates:

- Web workload.
- API workload.
- Database workload.

Each template defines a pinned image, non-root user, read-only filesystem where possible, dropped capabilities, resource requests/limits, health probes, stable labels, and approved ports.

### 6.3 Reference applications and traffic source

Replace the six-node School/Hospital fixture with a bounded, generic retail/vendor reference lab. Reuse only the Online Boutique services that materially contribute to the experiment; do not import all services merely because they exist.

| Tenant | Approved stack | Functional workflow |
|---|---|---|
| RetailCo | storefront, product catalogue, cart/cache, checkout, payment simulator, order database, maintenance gateway | Browse products, add to cart, checkout, record an order, and view order status |
| FacilitiesVendor | vendor portal, maintenance API, vendor database | Submit and review project-owned maintenance work orders |

The feasibility spike established that the upstream frontend and checkout dependency chain requires all 12 Online Boutique deployments unless SecureCloud maintains a fork or replacement stubs. The first working `retail-stack` therefore starts from the full pinned `v0.10.3` dependency set, then removes a service only after the adapted stack passes the same browse, cart, checkout, and load tests. Small SecureCloud-owned order persistence, maintenance gateway, vendor portal/API, and database components are added only where the experiment requires them. All imported source retains its Apache-2.0 notices. Branding remains generic and does not copy Target names, logos, assets, or trade dress. See [the feasibility record](RETAIL_FEASIBILITY.md).

The portal provisions these through two allowlisted composite stack definitions. Portal users still choose only safe catalog entries; they never submit images or raw Kubernetes YAML. Each service remains an independently labelled workload so Hubble can construct a meaningful temporal graph.

Default deny remains in force. One explicit, narrow cross-tenant business intent permits `vendor-api → retail-maintenance-gateway` on its declared port. It requires authorization from both tenant administrators and is versioned as policy evidence. No other vendor-to-retail edge is permitted.

Normal activity is generated by ordinary storefront use, the upstream load generator, and low-frequency vendor work-order activity. The web applications remain independently usable without SecureCloud. Preview access is routed through an authenticated, tenant-authorized backend endpoint; internal services and databases are not exposed directly.

In real API mode, the customer portal does not expose attack or traffic-simulation buttons. Security evidence comes from Hubble. A separate experiment harness under `backend/experiments/` executes allowlisted incident-inspired behaviours against project-owned namespaces and Services. It uses valid test credentials and real application requests, accepts scenario IDs rather than arbitrary commands or targets, and cannot address external systems.

The existing School/Hospital applications remain only as a regression fixture during migration and are removed from the primary demonstration after retail/vendor acceptance tests pass.

### 6.4 Enforcement sequence

1. Create one namespace per infrastructure tenant.
2. Apply restricted namespace security labels.
3. Apply default-deny ingress and egress.
4. Permit DNS.
5. Apply the versioned intra-tenant intents declared by the selected composite stack.
6. Deny cross-tenant communication by default.
7. Apply only the bilateral `vendor-api → retail-maintenance-gateway` exception.
8. Verify approved, default-denied, and explicitly cross-tenant-approved paths with positive and negative controls.
9. Persist Kubernetes UID and resource version on every managed workload.

### 6.5 Quarantine

Quarantine is durable desired state in SQLite. The reconciler reapplies it after pod replacement. Full quarantine withdraws all ingress and egress for the selected workload, including its previously approved paths; evidence and recovery remain available through the separate control plane.

Restore reapplies the workload's previously approved policy version and verifies both the restored approved path and continued forbidden-path denial.

---

## 7. Phase Five — Hubble Telemetry

Start with Hubble's built-in JSON flow exporter. It writes structured flow records with rotation, filtering, and field masks, avoiding a custom gRPC client in the first MVP. See [Hubble exporter configuration](https://docs.cilium.io/en/stable/observability/hubble/configuration/export/).

### 7.1 Collector

1. Read exported JSON flow records.
2. Validate and normalize fields.
3. Resolve namespaces/pods to stable tenant/workload IDs.
4. Deduplicate events.
5. Record explicit verdict and policy-denial reason.
6. Preserve unknown or unmapped events as inconclusive.
7. Feed valid events into the 30-second engine windows.

Use Hubble Relay's streaming gRPC API only if file-export latency becomes a measured limitation.

---

## 8. Phase Six — Incidents and Response

Incident states:

```text
open
→ containment_requested
→ contained
→ under_review
→ restore_requested
→ restored
→ closed
```

Each incident stores:

- Source and destination identities.
- Original Hubble event references.
- Graph anomaly score and threshold.
- Supporting security facts.
- Model and policy versions.
- Requested and executed actions.
- Containment verification.
- Restore verification.
- Actor and timestamps.

The frontend displays this evidence and exposes role-authorized quarantine and restore actions.

---

## 9. Phase Seven — Evaluation and Paper Data

### 9.1 Compared configurations

1. Static policy only.
2. Static policy plus edge-frequency baseline.
3. Static policy plus temporal-graph engine.

Use identical static policies and traffic for all comparable runs.

### 9.2 Scenarios

All scenarios run through the separate experiment harness. The portal remains the operator view for topology, evidence, incidents, quarantine, and restore.

**Benign:**

- Normal browsing, cart, checkout, order, and maintenance traffic.
- Legitimate shopping surge.
- Scheduled vendor maintenance burst.
- Workload restart.
- New approved deployment.
- Temporary service failure.

**Suspicious:**

- Cross-tenant attempt.
- Horizontal scan.
- Vertical port scan.
- Unexpected destination.
- Low-rate lateral movement.
- Compromised-vendor use of the valid maintenance path.
- Abnormal fan-out and ordering across policy-allowed service paths.
- Forbidden vendor-to-payment attempt after allowed-path reconnaissance.

### 9.3 Measurements

- Prevention rate.
- Precision, recall, F1, and false-positive rate.
- Precision-recall AUC.
- Detection latency.
- Predictive lead time relative to the first policy-denied event.
- Detection rate for policy-allowed malicious behaviour.
- Containment time.
- Recovery time.
- Approved-service disruption.
- Request latency and throughput overhead.
- Backend, Cilium, collector, and model CPU/memory usage.
- Model training and inference time.

Run at least 30 repetitions per scenario and five model seeds. Export raw events, ground truth, configuration, predictions, operations, and summaries as machine-readable JSONL/CSV.

### 9.4 Implemented evaluation artifacts

The current offline runner is `python -m backend.experiments.runner`. It executes the 11 allowlisted scenarios with 30 repetitions and five seeds by default and writes the following ignored runtime artifacts under `runtime/experiments/offline/`:

- `events.jsonl` — raw event-level policy verdicts and ground truth.
- `predictions.jsonl` — edge-frequency scores, thresholds, predictions, and labels.
- `runs.csv` — per-run prevention, classification, latency, and inference measurements.
- `summary.csv` and `summary.json` — per-scenario and overall metrics with 95% Wilson intervals.
- `manifest.json` — exact seeds, repetitions, scenarios, thresholds, implementation status, and limitations.

The currently implemented live runner is `python -m backend.experiments.live_runner`. It quarantines only `college-api` in the project-owned loopback K3s compatibility lab, brackets every run with positive School and Hospital controls, verifies Cilium policy read-back, observes withdrawal and recovery through the School application, and exports raw cycles plus timing distributions under `runtime/experiments/live/`. It must be migrated to allowlisted retail/vendor workload IDs after the new reference stack is operational.

The learned `GConvGRU` link predictor, chronological training, negative sampling, calibration, per-seed persistence, offline comparison, and continuous API-loop inference are implemented. The API loads a local weights-only checkpoint through `SECURECLOUD_TEMPORAL_MODEL`, rejects incompatible feature schemas, correlates model anomalies with explicit security facts, and persists model version, threshold, score, facts, and source-event IDs. With no configured checkpoint, the API explicitly reports and uses the edge-frequency baseline.

The implemented checkpoint and live pipeline are **not** the final general-purpose detector: their tenant one-hot features are coupled to College/Hospital, and online candidate selection currently emphasizes denied or cross-tenant flows. The next detector revision must remove tenant identity features, score all resolved traffic, add calibrated accumulated risk, retrain on the retail/vendor topology, and repeat the full evaluation. The current five-seed result in `backend/detection/model_card.md` does not outperform the edge-frequency baseline on the small fixed topology and must not be used as evidence of predictive improvement. CPU/memory overhead measurement remains pending.

---

## 10. Delivery Milestones

| Milestone | Deliverable | Feature coverage |
|---|---|---:|
| M1 | Kokonut console shell and API-backed authentication | 10% |
| M2 | Tenant, catalog, workload lifecycle, and operation status | 40% |
| M3 | Kubernetes deployment plus default-deny and approved paths | 60% |
| M4 | Retail/vendor reference stacks, Hubble telemetry, and tenant-agnostic temporal-graph incidents | 80% |
| M5 | Durable quarantine, restore, and evaluation dataset | 100% |

The 60% milestone is accepted only when the web portal deploys a real bounded workload and the lab verifies tenant-local allowed traffic, default cross-tenant denial, and the exact authorized vendor-to-maintenance exception with positive and negative controls.

### 10.1 Next implementation sequence

1. **Feasibility recorded:** version, licence, dependencies, immutable image digests, Kubernetes reservations, and a successful browse/cart/checkout transaction are recorded in [the retail feasibility report](RETAIL_FEASIBILITY.md). Steady-state consumption and Hubble flow counts remain pending because the local observability pods restarted during collection.
2. **Catalog definitions implemented:** the authenticated management API exposes fixed `retail-stack` and `facilities-vendor-stack` service graphs from `backend/catalog.py`. Callers cannot submit images or YAML. The API enables an action only when its infrastructure adapter is configured.
3. **Retail reconciler implemented and live-verified:** the portal can create one persisted composite operation, the Kubernetes adapter applies the pinned 12-service retail graph, and each component is retained as an independently observed workload with its Kubernetes UID and resource version. On 18 November 2026, the queued operation reconciled to `succeeded`, all 12 deployments reported `1/1` ready, the restricted namespace labels were read back, the real portal displayed all 12 components, and browse/cart/checkout completed through the deployed frontend.
4. **FacilitiesVendor reconciler implemented and live-verified:** the second allowlisted composite operation deploys a SecureCloud-owned web/API/PostgreSQL application with the `facilities-vendor` domain profile. On 18 November 2026, all three deployments reported `1/1` ready, the namespace retained restricted Pod Security and `securecloud.io/purpose=facilities-vendor-stack`, the portal rendered the three observed components and app link, and a work order created through the web proxy was read back from PostgreSQL.
5. **Live enforcement, telemetry, detection, and recovery verified:** on 20 November 2026, the FacilitiesVendor web-to-API and API-to-PostgreSQL paths succeeded while a FacilitiesVendor-to-RetailCo request received explicit Cilium/Hubble `DROPPED` verdicts. Stable workload identities were resolved with zero rejected records. The active edge-frequency baseline scored the new edge at `0.963` against a `0.600` threshold and persisted the incident and triggering flow. Authorized quarantine created a valid workload-scoped Cilium ingress/egress deny policy; review and restore removed it, replaced the affected web pod, and returned the previously approved path to HTTP 200. The final presentation state retains one fresh `vendor-api` alert and one completed `vendor-web` recovery trace. The learned temporal model is not configured in this run, so the portal and health endpoint explicitly identify `edge-frequency-v1` as the active detector.
6. **Regression evidence:** 75 backend tests, 22 frontend tests, the production frontend build, and the five-screen real Playwright presentation workflow pass. The two destructive real-cluster lifecycle integration tests remain opt-in.
7. Add explicit per-service RetailCo policies plus versioned bilateral approval for the single vendor-to-maintenance intent while retaining default deny everywhere else. The current RetailCo compatibility policy is intentionally labelled in the portal.
8. Replace tenant-name one-hot features with tenant-agnostic node and relational edge features.
9. Score all resolved flows, implement calibrated EWMA risk, and distinguish ML-only alerts from containment recommendations.
10. Implement the allowlisted compromised-vendor scenario using real requests and test credentials inside the project lab.
11. Retrain, recalibrate, and rerun 30 repetitions across five seeds against identical policy and traffic inputs.
12. Extend the portal incident trace and evaluation view with accumulated risk, prevention, predictive lead time, and containment metrics.
13. Retire School/Hospital from the primary demo only after equivalent lifecycle, policy, telemetry, containment, and recovery tests pass.

---

## 11. Architecture Decisions

### Composite stack persistence and reconciliation

**Context:** a composite catalog entry creates multiple independently observable Kubernetes workloads, but the portal must present one user operation and must be able to resume it after an API restart.

**Options considered:** flatten a stack into unrelated workload operations; store only one opaque stack row; or persist one stack deployment and operation while retaining a workload record for every component.

**Decision:** persist a stack deployment and stack operation for the user-level lifecycle request, and create one component workload record per catalog service. The reconciler owns the allowlisted stack graph and updates each component from positive Kubernetes observations.

**Rationale:** the user sees one bounded deployment action, while topology, telemetry identity, health, and later containment still operate on stable component workload IDs. Persisted operations allow restart-safe reconciliation without accepting raw images or manifests from callers.

**Trade-offs accepted:** stack and component state can temporarily differ while reconciliation is running, and stack lifecycle needs explicit orchestration rather than reusing a single-workload endpoint.

**Consequences and mitigation:** the database links every component to its stack; the operation remains pending until every expected Deployment is ready; missing or unknown observations do not become success; and tenant authorization is checked before infrastructure availability or mutation.

**Validation:** API boundary tests cover authorization, allowlisting, and fail-closed behaviour; adapter tests assert the exact 12-component inventory and namespace controls; a restart reconciliation was verified against the local K3s lab; and a non-mutating browser test verified that the API-backed portal renders the 12 observed components.

**Revisit trigger:** introduce a generic graph reconciler only after the FacilitiesVendor stack demonstrates shared lifecycle behaviour that cannot be expressed cleanly by the current bounded adapter.

### Backend shape

**Decision:** one FastAPI modular monolith.

**Reason:** the project is a small FYP demonstrator with one team and one lab. Separate services, brokers, and distributed transactions add no required research value.

### Telemetry transport

**Decision:** Hubble JSON exporter first; Hubble Relay gRPC only if required by measured latency.

**Trade-off:** file export is simpler but less immediate than a live stream.

### Model deployment

**Decision:** offline training and in-process backend inference.

**Trade-off:** the API process carries model dependencies, but the MVP avoids a model server and deployment coordination.

### Advanced detection

**Decision:** one temporal-graph link-prediction model using `GConvGRU`.

**Trade-off:** this provides a clear research feature while excluding a collection of unrelated detectors. A simple edge-frequency scorer remains only as the experimental baseline.

### Reference application and incident narrative

**Context:** the six-node School/Hospital graph is sufficient for lifecycle and policy tests but too small and regular to demonstrate a convincing independent contribution from temporal graph learning. Building a large custom microservice application would consume the project without adding security research value.

**Options considered:** retain School/Hospital; build a custom microservice system; deploy Online Boutique unchanged; maintain a fork with replacement stubs; or begin with the complete pinned dependency set and reduce it only behind functional acceptance tests.

**Decision:** use the complete, digest-pinned Online Boutique `v0.10.3` dependency set as the first known-working `RetailCo` stack, apply SecureCloud resource and security controls, add a SecureCloud-owned `FacilitiesVendor` stack, and use a Target-2013-inspired vendor-credential scenario. A service may be removed later only if the adapted stack still passes browse, cart, checkout, load, and telemetry tests.

**Rationale:** dependency inspection and a real checkout proved that the proposed six-service subset is not independently runnable without a maintained fork or stubs. Starting from the known-working graph avoids spending the FYP on application rewrites while providing repeatable traffic, permissively licensed source, and a credible valid-access-to-lateral-movement narrative within the two-tenant laboratory limit.

**Trade-offs accepted:** 12 imported deployments use more memory, image storage, and operational attention than the proposed subset; they also add multiple languages outside the team's application code. This is acceptable because the imported application remains a replaceable lab adapter and SecureCloud itself remains a modular monolith. The historical mapping remains an analogy rather than a forensic reconstruction.

**Consequences and mitigation:** final resource and flow measurements must include the full dependency graph; immutable digests and quotas bound supply-chain and capacity drift; explicit service-path policies replace the feasibility spike's broad same-namespace allowance; and a smaller fork is considered only if measured lab pressure prevents repeatable experiments.

**Validation:** pin images and source version; retain license notices; measure local CPU/memory; verify storefront and vendor workflows; verify the bilateral maintenance intent and all negative controls; demonstrate at least one allowed abnormal scenario; and compare temporal detection against static policy and edge-frequency baselines.

**Revisit trigger:** reduce or replace an imported service if the full stack exceeds the measured lab budget, cannot run with the required container hardening, or makes 30-repetition experiments unreliable.

### Tenant-agnostic temporal model

**Context:** tenant-name one-hot features couple a checkpoint to demo labels, and scoring only already denied/cross-tenant candidates makes the visible result predominantly rule-based.

**Options considered:** retain tenant one-hot features; train one model per named tenant pair; or use tenant-agnostic service and relationship features with deployment-local calibration.

**Decision:** use tenant-agnostic node features, relational same/cross-tenant and business-intent features, all-flow scoring, and calibrated EWMA risk on top of the existing GConvGRU anomaly score.

**Rationale:** one schema can support arbitrary portal tenants, the model can observe policy-allowed misuse, and accumulated risk makes temporal behaviour visible without adding another learned detector.

**Trade-offs accepted:** a deployment still needs a reviewed benign baseline; newly approved services can cause cold-start alerts; and automated containment requires corroborating facts rather than model score alone.

**Validation:** rename tenants without retraining the schema; test unseen workload IDs; measure allowed-path detection and false positives; use chronological splits; report predictive lead time; and retain deterministic policy-only and edge-frequency comparisons.

**Revisit trigger:** replace GConvGRU only if the corrected model still fails to beat the baseline or demonstrate useful predictive lead time under the richer held-out topology.

### Deferred items

- Mobile application.
- Landing and marketing pages.
- Billing and subscription workflows.
- Arbitrary container deployment.
- Tetragon runtime telemetry.
- Kafka, Celery, and control-plane microservices. Redis is permitted only where required by the bounded retail cart fixture.
- Full Euler framework import.
- LLM-generated incident decisions.
- Forensic checkpoint recovery.
- Multi-cluster and production-scale operation.

These items are reconsidered only after the end-to-end MVP and evaluation dataset are complete.

## 12. Risks and Validation Gates

| Risk | Validation gate |
|---|---|
| The bounded retail/vendor graph is still too small for useful temporal learning | Compare against edge frequency on held-out scenarios; retain the model claim only if it improves a declared metric or demonstrates useful predictive lead time |
| The model merely re-labels rule-detected events | Score all resolved allowed and denied flows; separately report allowed-path detections before the first policy denial |
| Tenant labels leak demo identity into the model | Exclude tenant names/IDs from learned features and pass tenant-renaming and unseen-workload tests |
| Imported Online Boutique services exceed the local lab budget | Measure the chosen subset under normal and peak load; remove nonessential services before weakening workload resource limits |
| The Target-inspired narrative is mistaken for an exact reconstruction | Cite primary testimony, state the uncertain historical path, use generic branding, and label every added step as a controlled project scenario |
| The vendor exception weakens tenant isolation | Require bilateral authorization, exact source/destination/port, policy versioning, audit evidence, and negative cross-tenant controls |
| Hubble file export adds excessive detection delay | Measure exporter-to-incident latency; switch to Hubble Relay gRPC only if the delay breaks the experiment target |
| UI migration breaks existing workflows | Migrate one complete tenant/workload vertical slice before replacing the remaining Fluent components |
| Quarantine exists in storage but not in the datapath | Verify withdrawal of a previously allowed connection and repeat after pod replacement |
| Policy changes leave established connections active | Test both new and established connections and record the observed Cilium behaviour |
| Training data accepts attack traffic as normal | Use reviewed benign training periods, immutable dataset manifests, chronological splits, and model-version records |
| Model dependencies exceed the lab budget | Measure training/inference CPU, memory, and latency before enabling continuous scoring |
| The demonstrator looks like a scripted attack toy | Keep scenario controls outside the customer portal; show ordinary reference-app use, live Hubble evidence, and independently verified policy outcomes |
| Imported and SecureCloud-owned services use inconsistent identity labels | Enforce one catalog label contract and reject unresolved workload identity as inconclusive rather than scoring it |
