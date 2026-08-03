# SecureCloud MVP Implementation Plan

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

The infrastructure demonstrator supports two tenants and three templates: web, API, and database. The frontend data model is not restricted to two tenants.

## 2. Repository Layout

```text
actualfyp/
├── frontend/                 # React web application
│   ├── src/
│   ├── public/
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

Use PyTorch Geometric Temporal rather than importing the full Euler research codebase. PyTorch Geometric Temporal provides temporal snapshot iterators and reusable recurrent graph layers, including `GConvGRU`, under the MIT license. See the [project repository](https://github.com/benedekrozemberczki/pytorch_geometric_temporal) and [`GConvGRU` documentation](https://pytorch-geometric-temporal.readthedocs.io/en/stable/modules/root.html).

### 4.2 Graph definition

Create one directed graph snapshot every 30 seconds.

**Nodes:** stable SecureCloud workload IDs, not pod IP addresses.

**Node features:**

- Template type: web, API, or database.
- Tenant identity encoded without treating tenant number as an ordered value.
- Inbound flow count.
- Outbound flow count.
- Denied-flow ratio.
- Unique destination count.
- Unique destination-port count.
- Workload running/quarantined state.

**Edges:** observed source-to-destination communication.

**Edge features:**

- Flow count.
- Allowed count.
- Denied count.
- Destination port.
- Protocol.
- Approved-path indicator.
- Cross-tenant indicator.

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

The graph anomaly score is the main learned signal. Four explicit facts accompany it:

- Cross-tenant attempt.
- Policy-denied verdict.
- Horizontal destination fan-out.
- Vertical port fan-out.

The MVP incident rule is:

```text
Create an incident when:
  calibrated graph anomaly threshold is exceeded
  AND at least one explicit security fact is present
```

The detector does not write Cilium policies. It creates evidence and a containment recommendation. The authorized middleware operation applies or restores policy.

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

### 6.3 Enforcement sequence

1. Create one namespace per infrastructure tenant.
2. Apply restricted namespace security labels.
3. Apply default-deny ingress and egress.
4. Permit DNS.
5. Permit web-to-API communication within the tenant.
6. Permit API-to-database communication within the tenant.
7. Deny cross-tenant communication.
8. Verify approved and forbidden paths with explicit controls.
9. Persist Kubernetes UID and resource version on every managed workload.

### 6.4 Quarantine

Quarantine is durable desired state in SQLite. The reconciler reapplies it after pod replacement. Full quarantine withdraws previously approved workload access while retaining only the minimum management path needed for health/evidence collection.

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

**Benign:**

- Normal web-to-API-to-database traffic.
- Legitimate traffic surge.
- Workload restart.
- New approved deployment.
- Temporary service failure.

**Suspicious:**

- Cross-tenant attempt.
- Horizontal scan.
- Vertical port scan.
- Unexpected destination.
- Low-rate lateral movement.
- Suspicious use of a previously approved path.

### 9.3 Measurements

- Prevention rate.
- Precision, recall, F1, and false-positive rate.
- Precision-recall AUC.
- Detection latency.
- Containment time.
- Recovery time.
- Approved-service disruption.
- Request latency and throughput overhead.
- Backend, Cilium, collector, and model CPU/memory usage.
- Model training and inference time.

Run at least 30 repetitions per scenario and five model seeds. Export raw events, ground truth, configuration, predictions, operations, and summaries as machine-readable JSONL/CSV.

---

## 10. Delivery Milestones

| Milestone | Deliverable | Feature coverage |
|---|---|---:|
| M1 | Kokonut console shell and API-backed authentication | 10% |
| M2 | Tenant, catalog, workload lifecycle, and operation status | 40% |
| M3 | Kubernetes deployment plus default-deny and approved paths | 60% |
| M4 | Hubble telemetry plus temporal-graph incidents | 80% |
| M5 | Durable quarantine, restore, and evaluation dataset | 100% |

The 60% milestone is accepted only when the web portal deploys a real bounded workload and the lab verifies tenant-local allowed traffic and forbidden cross-tenant traffic.

---

## 11. Architecture Decisions

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

### Deferred items

- Mobile application.
- Landing and marketing pages.
- Billing and subscription workflows.
- Arbitrary container deployment.
- Tetragon runtime telemetry.
- Kafka, Redis, Celery, and microservices.
- Full Euler framework import.
- LLM-generated incident decisions.
- Forensic checkpoint recovery.
- Multi-cluster and production-scale operation.

These items are reconsidered only after the end-to-end MVP and evaluation dataset are complete.

## 12. Risks and Validation Gates

| Risk | Validation gate |
|---|---|
| The two-tenant graph is too small for a useful temporal model | Compare against edge frequency on held-out scenarios; retain the model only if it improves precision/recall or detection delay |
| Hubble file export adds excessive detection delay | Measure exporter-to-incident latency; switch to Hubble Relay gRPC only if the delay breaks the experiment target |
| UI migration breaks existing workflows | Migrate one complete tenant/workload vertical slice before replacing the remaining Fluent components |
| Quarantine exists in storage but not in the datapath | Verify withdrawal of a previously allowed connection and repeat after pod replacement |
| Policy changes leave established connections active | Test both new and established connections and record the observed Cilium behaviour |
| Training data accepts attack traffic as normal | Use reviewed benign training periods, immutable dataset manifests, chronological splits, and model-version records |
| Model dependencies exceed the lab budget | Measure training/inference CPU, memory, and latency before enabling continuous scoring |
