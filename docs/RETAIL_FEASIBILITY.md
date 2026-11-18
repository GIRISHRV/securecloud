# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation

## Online Boutique feasibility record

**Recorded:** 18 November 2026  
**Verdict:** Application feasibility passed; steady-state telemetry measurement remains pending because the local K3s system services repeatedly restarted during the measurement window.

## Source and licence

| Item | Recorded value |
|---|---|
| Upstream project | Google Cloud Online Boutique (`GoogleCloudPlatform/microservices-demo`) |
| Licence | Apache-2.0 |
| Release | `v0.10.3` |
| Commit | `cd1cb59f6fce3e2ccf08be7cea743e3784932d73` |
| Source manifest | `release/kubernetes-manifests.yaml` |
| Manifest SHA-256 | `681b58e962f9fb1fa49854483f98ac52b01f53bae6fad7868dc758abcff86354` |
| Spike namespace | `sc-retail-spike` |

The upstream source is retained only in the ignored `runtime/vendor-spikes/` workspace. `backend/experiments/retail_spike.py` refuses to transform a manifest whose hash does not match the recorded source.

## Dependency result

The proposed six-service subset is not runnable without maintaining a fork or replacement stubs. The upstream frontend connects to catalogue, currency, cart, recommendation, shipping, checkout, and advertising services. Checkout also connects to payment and email services. The feasibility deployment therefore used all 12 upstream deployments:

`adservice`, `cartservice`, `checkoutservice`, `currencyservice`, `emailservice`, `frontend`, `loadgenerator`, `paymentservice`, `productcatalogservice`, `recommendationservice`, `redis-cart`, and `shippingservice`.

This does not make all 12 services permanent SecureCloud scope. It establishes the known-working reference point from which a smaller maintained adaptation can be measured.

## Security transformation

The generated spike manifest:

- removes the upstream external `LoadBalancer` service;
- applies restricted Pod Security labels to the namespace;
- disables service-account token mounting;
- applies `RuntimeDefault` seccomp;
- preserves the upstream non-root, dropped-capability, and read-only filesystem settings;
- pins every application, Redis, and init-container image by SHA-256 digest;
- supplies resource requests and limits to init containers;
- enforces a namespace quota;
- applies default-deny, same-namespace, and DNS network policies; and
- adds stable SecureCloud tenant and workload labels.

The same-namespace policy is intentionally broad for this dependency feasibility test. It is not the final least-privilege retail policy.

## Resource evidence

The local node reported 24 allocatable CPU cores and `7936976Ki` allocatable memory. Kubernetes admitted 12 pods with the following aggregate reservations:

| Measurement | Value |
|---|---:|
| CPU requests | 1570m |
| CPU limits | 2825m |
| Memory requests | 1368Mi |
| Memory limits | 2542Mi |
| Namespace quota | 2 CPU / 2Gi requested; 4 CPU / 4Gi limited; 20 pods |

These values are requested and limited capacity, not observed consumption. `metrics-server` and Hubble Relay repeatedly stopped during the final collection window after local K3s/WSL restarts, so steady-state CPU/memory and Hubble flow counts are explicitly inconclusive and must be collected in a stable run.

## Immutable image inventory

| Workload image | Recorded digest |
|---|---|
| adservice | `sha256:ff1a059bb8f1226b77b42a9102344cfc4b669a04696eb44aeed3db8ae2b04e9e` |
| cartservice | `sha256:598efe871d0251cbd35729972acb23c0723cb7aca451503ba10fb8116aecb958` |
| checkoutservice | `sha256:6688da8718a92373cc149c8423936b342123060e86705804f9ffbc421bd2ae8f` |
| currencyservice | `sha256:f7d6e530d10ecbf8a10408bd6e114ed6d7670130bb28d22309bb66fcb99ebdb9` |
| emailservice | `sha256:59558f8e668e4edec7b40a928c2368696474a8da85ef912e278f8abb3200ecbe` |
| frontend | `sha256:83f44050fc5ea5999ea04a940e687d7bd5ad357fcf6e6f5944e5e32de006bbdb` |
| loadgenerator | `sha256:49fc8f2312d72c6e61b697d378601cfc53f30af3cdbbc7c105759c0024d0c456` |
| paymentservice | `sha256:d95567da89a5e7c3c819f1b742c12a3bf4a2ad35af0ddbcbd06eb908252e67d9` |
| productcatalogservice | `sha256:c358001d318f6bec85f49119653f19bbc235a0a323e45c936dc74460701fd129` |
| recommendationservice | `sha256:2f3eae327b743160033cec8662362e2190f9aa9a04a1ace1bd05f19106ed4bd3` |
| shippingservice | `sha256:b0125be448f9eb042214fec6eebda79a900a1a4c307f8e1bdb56f35e403969dd` |
| Redis | `sha256:6aaf3f5e6bc8a592fbfe2cccf19eb36d27c39d12dab4f4b01556b7449e7b1f44` |
| BusyBox init container | `sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662` |

## Functional evidence

After all 12 deployments rolled out, a test client connected directly to the internal frontend service through a temporary local port-forward and completed the following real application workflow:

| Check | Result |
|---|---|
| Storefront home page | HTTP 200 |
| Product detail (`OLJCESPC7Z`) | Loaded |
| Add to cart | Succeeded |
| Checkout | HTTP 200 |
| Order confirmation | Present |

Checkout used Online Boutique's published fake test card inside the project-owned lab. No external target or real credential was used. The temporary port-forward was stopped after the check.

## Decision and remaining gate

Online Boutique is viable as the functional RetailCo base and provides a sufficiently rich service graph. The management plane now exposes it through an allowlisted `retail-stack` definition using the full known-working dependency set. Before calling the retail stack accepted, the project must still:

1. replace the broad same-namespace policy with explicit service paths;
2. collect Hubble flow evidence and observed CPU/memory during a stable run;
3. add the SecureCloud-owned order persistence and maintenance gateway where required by the experiment;
4. add the independently usable FacilitiesVendor stack; and
5. verify the single bilateral vendor-to-maintenance path plus negative controls.

## Management-plane integration evidence

On 18 November 2026, the feasibility transform was connected to the authenticated SecureCloud management plane as the bounded `retail-stack` adapter.

| Check | Observed result |
|---|---|
| User-level deployment | One persisted composite stack operation reconciled to `succeeded` |
| Component identity | 12 component workload records, each with a distinct observed Kubernetes UID |
| Kubernetes readiness | 12 Deployments at `1/1` ready in the managed tenant namespace |
| Namespace controls | Restricted Pod Security labels and `securecloud.io/purpose=retail-stack` read back from Kubernetes |
| Portal integration | Authenticated API-mode browser test rendered exactly 12 RetailCo workload rows |
| Functional transaction | Home, product, cart, and checkout returned HTTP 200; response contained `Your order is complete` |

This verifies deployment and positive application behaviour, not final zero-trust acceptance. The current imported graph still uses the feasibility policy set; explicit per-service intents, the vendor exception, Hubble evidence, and positive/negative policy controls remain required.

