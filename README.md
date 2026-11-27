# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation

An Azure-like self-service private-cloud prototype on Kubernetes, with a built-in zero-trust
security plane. Shops are tenants: each runs in its own isolated namespace behind default-deny
network policy. When one is compromised, SecureCloud blocks the attacker's lateral movement,
detects the behaviour with a temporal-graph model, and quarantines the affected workload.

## Live demo

**https://securecloud-wake-qudb8c.azurewebsites.net**

The lab sleeps when nobody is using it. This link wakes it and shows a boot screen for about
3 minutes, then forwards you to the live site at https://74-225-145-124.sslip.io.

| Public guest login | |
|---|---|
| Email | `guest@74-225-145-124.sslip.io` |
| Password | `n3iAGrgUVnRjLF3JQg` |

The guest login is public on purpose. The server lets it explore the provider console, run the
attack lab and quarantine/restore **testbed** workloads. It cannot remove, pause or reconfigure
shops, open shops, or see merchants' email addresses. Everyone shares one demo, so you may see
someone else's attack in progress. It goes back to sleep after 30 minutes without visitors.

### Try it in two minutes

1. Open **[/lab](https://74-225-145-124.sslip.io/lab)** and click **Sign in as guest**.
2. Launch an attack, for example *Plugin attacks the other shop*. The default-deny policy drops it
   and Hubble records the verdict.
3. Open **[/admin](https://74-225-145-124.sslip.io/admin)** to see the alert, the live service graph
   and the evidence; quarantine the compromised plugin and watch its access withdrawn.
4. Visit **[Northstar](https://74-225-145-124.sslip.io/northstar/shop)** to place an order and
   watch the traffic appear, or register your own account and open a shop at
   **[/start](https://74-225-145-124.sslip.io/start)**.

## What it does

| Flow | What you can see |
|---|---|
| Self-service tenant lifecycle | Merchants open a shop from one allowlisted template; it is provisioned as its own namespace with quotas, restricted Pod Security and default-deny policy. Pause, resume and removal are authorised, idempotent and verified. |
| Enforcement, detection and containment | Cilium enforces per-tenant policy; Hubble flow telemetry feeds a temporal-graph link-prediction detector (GConvGRU), corroborated with policy denials and cross-tenant attempts. Quarantine survives reconciliation and pod replacement; restore is audited. |

The attack lab runs synthetic attacks inside the cluster only and scores prevention, detection,
false positives and containment time. Results are never inferred from a timeout; unobserved or
ambiguous outcomes are reported as inconclusive.

## Stack

K3s · Cilium + Hubble (eBPF) · FastAPI modular monolith · SQLite · PyTorch Geometric ·
React + Vite + TypeScript · Caddy (HTTPS)

## Run your own

On a fresh Ubuntu 24.04 VM (2 vCPU, 4 GB), with ports 80 and 443 open:

```bash
curl -fsSL https://raw.githubusercontent.com/GIRISHRV/securecloud/main/deploy/install.sh | sudo bash
```

It installs everything, provisions the testbed shops, gets an HTTPS certificate for
`<your-ip>.sslip.io`, and prints generated logins. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
for details and the local Windows + WSL lab.

## Limitations

Containers stand in for virtual machines; this is a single-node lab with synthetic attack traffic.
Namespace isolation is soft multi-tenancy and does not replace a cloud provider's own tenant
isolation. The project addresses post-compromise lateral movement between organisation-managed
workloads; it does not claim that public clouds expose one customer to another.
