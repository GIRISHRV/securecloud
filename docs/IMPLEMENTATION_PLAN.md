# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation — Implementation Plan

## 1. Final Product

SecureCloud will be demonstrated through two visible experiences:

1. **Customer storefront** — registration, login, products, cart, checkout, and order history.
2. **Unified shop-owner dashboard** — customers, active sessions, products, orders, service health, suspicious activity, incidents, quarantine, and restore.

Kubernetes, Cilium, Hubble, the temporal-graph detector, and the response controller run behind these interfaces.

~~~text
Alice completes a real order
→ the order and session appear in the owner dashboard
→ a vendor uses approved maintenance access normally
→ a controlled compromise changes its request pattern
→ SecureCloud correlates session, request, and Hubble evidence
→ temporal risk rises
→ Cilium blocks a forbidden vendor-to-payment connection
→ the owner receives an alert
→ the owner quarantines the vendor API
→ vendor access is withdrawn while Alice's storefront remains healthy
→ the owner restores the previous approved policy
~~~

This is an FYP demonstrator for organization-managed container workloads. It is not a public-cloud replacement or production SOC.

## 2. Scope

### Included

- Functional retail accounts, sessions, catalogue, cart, checkout, payment simulation, and detailed orders.
- Unified admin UI based on [the approved mockup](../mockups/unified-admin-dashboard.html).
- Existing K3s, Cilium, Hubble, temporal detector, policy, quarantine, and restore implementation.
- Application-request and workload-flow correlation.
- Edge-frequency scoring as the experimental baseline.
- Controlled attack traffic restricted to the project lab.
- Local backend with an optional Vercel frontend through an authenticated HTTPS tunnel.

### Deferred

- Mobile, billing, arbitrary containers/YAML, real payments, multi-region operation, and production scale.
- AKS/GKE/EKS deployment.
- Training on unreviewed live traffic.
- Automated destructive response based only on ML.
- Claims that the demonstration reconstructs a historical breach.

## 3. Current Baseline

| Area | Evidence | Status |
|---|---|---|
| SecureCloud API | backend/api.py: auth, tenants, workloads, stacks, traffic, incidents, response | Implemented |
| Persistence | backend/store.py | Implemented |
| Kubernetes response | backend/infrastructure/kubernetes.py | Implemented for the lab |
| Lab automation | backend/manifests/lab | Implemented for Windows/WSL2 |
| Hubble ingestion | backend/telemetry | Implemented |
| Temporal detector and baseline | backend/detection | Implemented offline |
| Evaluation | backend/experiments | Implemented offline |
| Existing cloud/security portal | frontend/src | Implemented; becomes a technical/operator section |
| Retail/vendor provisioning | catalog and reference-lab code | Partial |
| Functional retail domain | Customer/owner auth, products, carts, idempotent checkout, detailed orders, sessions, admin APIs | Implemented with the local SQLite adapter; PostgreSQL deployment adapter remains |
| Customer storefront | `/shop` registration, sign-in, catalogue, product, cart, checkout, payment receipt, and order history | Implemented and browser-tested at desktop and mobile widths |
| Unified business dashboard | `/admin` owner auth, overview, customers/sessions, products, orders, service health, and fulfilment transitions | Implemented and browser-tested at desktop and mobile widths; security evidence joins in M5 |
| User/request/flow correlation | Trusted request IDs, bounded application events, retained actor/session references, and exact/inconclusive joins to normalized flows | Implemented for the local runtime; vendor scenario integration remains in M6 |
| Vercel frontend | Build and tunnel configuration | Not implemented |

Rerun tests at every milestone. Old test counts are not current evidence.

## 4. Architecture

~~~text
Customer browser                   Shop-owner browser
       └──────── React/Vite frontend ────────┘
                 storefront + /admin
                          │
                          ▼
                  Retail gateway/BFF
          auth · cart · checkout · orders · audit
                    │                  │
                    ▼                  ▼
             Retail services       PostgreSQL
                    │
             Cilium enforcement
                    │
             Hubble flow records
                    │
                    ▼
            SecureCloud middleware
       normalize · correlate · score · respond
                    │
                    ▼
             Admin security views
~~~

### Boundaries

- The **retail plane** owns customers, sessions, products, carts, orders, payments, and application events.
- The **SecureCloud plane** owns tenants, workloads, intent, flows, risk, incidents, quarantine, and restore.
- The UI calls authenticated APIs; it never joins databases directly.
- Kubernetes is internal. Users never submit manifests.
- Customer, shop-owner, vendor, and platform-operator authorization remain distinct.

## 5. Target Modules

~~~text
frontend/src/
├── storefront/      catalogue, cart, checkout, customer orders
├── admin/           overview, orders, customers, products
├── security/        activity, incidents, evidence, response
├── services/        typed retail and SecureCloud clients
└── domain/          schemas and view models

backend/
├── api.py           existing SecureCloud boundary
├── retail/
│   ├── api.py       customer and owner endpoints
│   ├── auth.py      accounts and sessions
│   ├── repository.py
│   ├── cart.py
│   ├── checkout.py
│   ├── orders.py
│   └── audit.py
├── correlation/     event schema, ingestion, correlation
├── detection/       existing temporal detector and baseline
├── telemetry/       existing Hubble ingestion
└── infrastructure/  existing Kubernetes adapter
~~~

Add modules only when their implementation milestone starts.

## 6. Retail Data

The logical schema below is implemented by the repeatable local SQLite migration in `backend/retail/store.py`. A PostgreSQL repository using the same contract remains part of the deployment milestone; the local adapter is the verified M0/M1 runtime.

Use PostgreSQL tables:

~~~text
retail_users
retail_sessions
customer_addresses
products
carts
cart_items
orders
order_items
payments
application_events
~~~

Orders retain customer, delivery-address, SKU, product-name, price, quantity, payment-reference, and status snapshots. Later profile or product edits must not rewrite historical orders.

Application events contain only request ID, actor/session references, workload identities, bounded action, result, tenant, and timestamp. Passwords, tokens, addresses, and payment details never enter telemetry or model artifacts.

## 7. API Contract

### Customer

~~~text
POST   /api/retail/auth/register
POST   /api/retail/auth/login
POST   /api/retail/auth/logout
GET    /api/retail/auth/session
GET    /api/retail/products
GET    /api/retail/products/{id}
GET    /api/retail/cart
POST   /api/retail/cart/items
PATCH  /api/retail/cart/items/{id}
DELETE /api/retail/cart/items/{id}
POST   /api/retail/checkout
GET    /api/retail/orders
GET    /api/retail/orders/{id}
~~~

### Shop owner

~~~text
GET    /api/retail/admin/overview
GET    /api/retail/admin/customers
GET    /api/retail/admin/sessions
GET    /api/retail/admin/products
POST   /api/retail/admin/products
PATCH  /api/retail/admin/products/{id}
GET    /api/retail/admin/orders
GET    /api/retail/admin/orders/{id}
PATCH  /api/retail/admin/orders/{id}/status
GET    /api/retail/admin/activity
GET    /api/retail/admin/security/summary
~~~

Existing SecureCloud incident endpoints remain the response boundary.

All mutations require authenticated role and tenant authorization, strict validation, CSRF protection where applicable, idempotency, and an audit event.

## 8. UI/UX

Storefront routes:

~~~text
/
/products/{id}
/cart
/checkout
/account/orders
/account/orders/{id}
/login
/register
~~~

Admin routes:

~~~text
/admin/overview
/admin/orders
/admin/customers
/admin/products
/admin/security
/admin/incidents/{id}
/admin/services
~~~

Port the mockup into the existing React, TypeScript, Tailwind, shadcn, and Kokonut stack.

The owner overview shows orders, revenue, active customers, open orders, incidents, blocked requests, recent orders, combined activity, and service health.

Incident details show:

- Actor and session reference.
- Source and destination workloads.
- Request and Hubble evidence.
- GNN score, EWMA risk, threshold, and frequency baseline.
- Independent facts such as policy denial or scan fan-out.
- Response state and authorized actions.

UI rules:

- Use dense tables and bordered sections, not decorative card grids.
- Put plain shop-owner language before technical evidence.
- Never describe an ML-only score as a confirmed attack.
- Distinguish allowed, denied, unknown, quarantined, and restored.
- Poll summaries every 3–5 seconds; do not add WebSockets for the MVP.
- Support keyboard access, visible focus, mobile navigation, and loading/error/offline states.
- Validate API responses with typed schemas.

## 9. Application-to-Security Bridge

The gateway strips caller-supplied context headers, then generates trusted values:

~~~text
X-Request-ID
X-SecureCloud-Tenant
X-SecureCloud-Actor-Ref
X-SecureCloud-Session-Ref
~~~

A security-relevant action emits a bounded event after its result is known.

Correlation uses stable source/destination workload IDs, event time, protocol, port, and request ID when available. An ambiguous join remains inconclusive; timing alone is not proof that a user caused a network flow.

Incidents store references to application events and normalized flows plus model version, raw anomaly, accumulated risk, threshold, policy facts, and response status. The authorized admin API resolves the display name.

## 10. Detection and Response

Reviewed benign activity includes browsing, cart changes, checkout, administration, health checks, and scheduled vendor maintenance.

An administrator-only lab command makes the vendor workload:

1. Use its approved maintenance path at unusual frequency.
2. Contact unusual retail destinations or ports.
3. Attempt a forbidden payment-service connection.

~~~text
application event + normalized Hubble flow
→ graph window
→ temporal link anomaly
→ EWMA accumulated risk
→ calibrated threshold
→ independent policy/scanning facts
→ alert
→ containment recommendation only when the fact gate passes
~~~

Cilium prevents forbidden paths. Temporal scoring detects abnormal use of still-permitted paths. The model never writes policy.

Quarantine saves prior intent, denies workload ingress and egress, survives reconciliation/pod replacement, and requires positive verification. Timeouts remain inconclusive. Restore reapplies and verifies the previous path.

## 11. Milestones

### M0 — Contracts and guardrails — complete for the local runtime

- Freeze retail, application-event, correlation, and admin schemas.
- Add migrations and explicit demo-data commands.
- Record current backend/frontend test results.
- Keep the existing portal behind role-based operator navigation.

**Exit:** migrations repeat cleanly and existing tests pass.

### M1 — Functional retail backend — complete for the local runtime

- Implement customer/owner accounts, secure sessions, products, addresses, cart, checkout, payment simulation, and detailed orders.
- Make checkout transactional and idempotent.
- Add ownership and owner-role tests.

**Exit:** Alice completes checkout through APIs and the stored order has complete snapshots.

### M2 — Customer storefront — complete for the local runtime

- Build authentication, catalogue, product, cart, checkout, and order-history screens.
- Add validation and a browser test from registration to reopened order. The Playwright journey now passes at desktop and mobile widths.

**Exit:** a reviewer places and reopens an order without developer tools.

### M3 — Unified business admin — complete for the local runtime

- Port the approved mockup to React.
- Implement overview, customers, sessions, products, orders, and service health.
- Add audited order-status transitions.
- Keep security controls linked to the technical console until the M5 evidence and response integration is complete.

**Exit:** Alice's active session and full order appear in the owner dashboard.

### M4 — Identity and flow correlation — complete for the local runtime

- Add trusted request propagation and bounded events.
- Implement validation, deduplication, retention, and Hubble correlation.
- Extend incident evidence with actor/session references.
- Strip caller-supplied context headers and derive request, tenant, actor, and session references from the authenticated server-side context.
- Preserve unmatched and ambiguous joins as non-proof states instead of attributing them to a user.

**Exit:** checkout traces from session to application requests and resolved workload flows.

### M5 — Unified security workflow — complete for the local runtime

- Implement security summary, activity, incident evidence, polling, offline states, and response controls.
- Connect existing quarantine, review, and restore endpoints.
- Scope owner-visible incidents to the explicitly deployed retail/vendor lab and require a corroborated containment recommendation before quarantine.
- Preserve infrastructure failures and missing verification as visible errors rather than successful response claims.

**Exit:** the owner investigates and responds without the legacy console.

### M6 — Controlled compromise and containment

- Establish benign vendor traffic.
- Run abnormal allowed traffic and the forbidden payment attempt.
- Create the incident from temporal risk plus independent facts.
- Verify withdrawal, unrelated checkout success, and restore.

**Exit:** the complete scenario passes from a clean start three times.

**Status (24 November 2026) — live lab implemented, partially verified.** The owner admin has a **Live lab** page (`backend/lab`, `/api/retail/admin/lab/*`). It runs five allowlisted scenarios by executing server-built probe scripts inside the real source pod (`pods/exec`, lab-only RBAC rule) and takes every verdict from ingested Hubble flows; a probe's own timeout is shown as the client view and never counted as enforcement. Single runs in the K3s lab observed:

- Real checkout from `loadgenerator`: order completed, 33–36 FORWARDED flows plus the downstream checkout/payment/cart/shipping hops.
- `vendor-api` → RetailCo payment, cart, checkout, redis: 42 DROPPED (`POLICY_DENIED`), GNN risk 0.93–1.00, containment recommended, incident opened.
- `vendor-api` port scan of `vendor-database`: 5432 FORWARDED, the other seven ports DROPPED.
- Quarantine verified in 1.1–3.0 s; the previously approved `vendor-api` → `vendor-database:5432` path then DROPPED (`POLICY_DENY`); restore returned it to FORWARDED.

Fixes found by the live runs: the quarantine policy blocked kubelet probes and crash-looped the pod (now only the local `host` identity may connect inbound); forwarded Hubble reply legs were ingested as reverse edges and, together with an approved-edge set that ignored catalog stack dependencies, scored normal checkout traffic at 0.999 (now 0.26–0.32); findings now attach to the source's open incident instead of opening one incident per edge; the collector resumes near the end of large captures after a restart. Still pending for the exit criterion: three clean-start repetitions, the valid-path-misuse scenario evaluated against detection lead time, and the bilateral vendor-maintenance exception.

### M7 — Packaging and optional Vercel frontend

- Update the root launcher for retail, SecureCloud, collector, inference, K3s, and forwards.
- Add aggregate readiness and actionable failures.
- Expose only authenticated HTTP ingress through HTTPS.
- Add Vercel build and same-origin API rewrite.
- Keep a local frontend fallback.

**Exit:** the hosted frontend works without exposing PostgreSQL, Kubernetes API, Hubble Relay, or debug ports.

## 12. Tests and Research Measurements

Functional/security tests cover sessions, ownership, stock, idempotent checkout, duplicate-payment prevention, cross-customer access, vendor/owner separation, forged context headers, CSRF, limits, invalid transitions, and secret/PII exclusion.

Kubernetes verification proves:

- Normal checkout and vendor maintenance work before the scenario.
- Vendor-to-payment produces an explicit Hubble policy denial.
- Quarantine survives reconciliation and pod replacement.
- Vendor maintenance fails after quarantine.
- Customer checkout still works.
- Vendor maintenance works after restore.
- Missing evidence remains inconclusive.

| Metric | Definition |
|---|---|
| Prevention rate | Explicit denials / forbidden attempts |
| Precision and recall | Incident classification on held-out scenarios |
| False-positive rate | Benign windows alerted / benign windows |
| Alert latency | First qualifying event to persisted incident |
| Correlation coverage | Resolved app-flow joins / eligible events |
| Containment time | Quarantine request to verified withdrawal |
| Recovery time | Restore request to verified access |
| Customer disruption | Failed benign checkouts during containment / benign checkouts |
| Policy overhead | Latency/throughput against identical baseline policy |

Temporal and edge-frequency evaluations use identical static policies and held-out traffic. Report confidence intervals and inconclusive runs.

## 13. Deployment

Supported backend:

~~~text
Windows 11 → WSL2 Ubuntu → K3s → Cilium/Hubble
→ retail, vendor, SecureCloud, and PostgreSQL workloads
~~~

Optional hosted frontend:

~~~text
Vercel HTTPS frontend
→ same-origin /api rewrite
→ stable authenticated HTTPS tunnel
→ local FastAPI ingress
→ local Kubernetes services
~~~

Only HTTP ingress is exposed. A hosted UI is not evidence that the middleware is online; the dashboard must show backend-offline state.

## 14. Architecture Decisions

- **Unified owner dashboard:** joins business and security view models, not databases.
- **Retain Kubernetes/Cilium/Hubble:** preserve real enforcement and telemetry; simplify operation through scripts.
- **Retail gateway:** centralize browser authorization, request context, idempotency, and audit emission.
- **Bounded event bridge:** prevent SecureCloud from reading unrestricted customer tables; allow inconclusive correlation.
- **Vercel plus local backend:** provide a shareable UI without managed-Kubernetes cost; retain local fallback.
- **Polling first:** reduce operational complexity until measured latency requires another transport.
- **Modular monolith control plane:** do not add brokers or control-plane microservices without a measured need.

## 15. Demo-Ready Definition

The project is ready only when, from a clean start:

1. The launcher reports every required component healthy.
2. Alice signs in, places an order, and reopens it.
3. The owner sees Alice's session and complete order.
4. Normal vendor maintenance succeeds.
5. The controlled compromise generates abnormal allowed traffic and a forbidden payment attempt.
6. Hubble records an explicit denial.
7. SecureCloud stores score, risk, threshold, facts, source events, and model version.
8. The unified dashboard shows one understandable alert with expandable evidence.
9. The owner quarantines the vendor in that dashboard.
10. Vendor access is positively verified as withdrawn.
11. Alice can still browse and check out.
12. Restore returns the approved vendor path.
13. Evidence remains available after restore.
14. Backend, frontend, browser, and isolated-lab tests pass.

Anything not proven by these checks remains planned or inconclusive.
