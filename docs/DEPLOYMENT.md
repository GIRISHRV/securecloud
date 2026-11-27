# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation — Deployment

This guide deploys the lab demonstrator: a single-node K3s cluster with Cilium/Hubble, the
FastAPI control plane, and the React portal. It is a lab deployment for an isolated,
project-owned machine. It is not a production hardening guide.

## Public hosting on Azure for Students (free, no credit card)

1. In the Azure portal create a VM: **Ubuntu Server 24.04 LTS**, size **Standard_B2s** (2 vCPU, 4 GB),
   authentication with an SSH key. Under *Networking*, allow inbound **SSH (22), HTTP (80), HTTPS (443)**.
2. Open the VM's **public IP** resource → *Configuration* → set a **DNS name label** (for example
   `securecloud-demo`). Your domain becomes `securecloud-demo.<region>.cloudapp.azure.com`.
3. SSH in and run:

   ```bash
   sudo git clone https://github.com/GIRISHRV/securecloud.git /opt/securecloud
   sudo /opt/securecloud/deploy/setup.sh securecloud-demo.<region>.cloudapp.azure.com
   ```

   The first run takes about 15 minutes and prints the generated demo logins once (they are also
   kept in `/etc/securecloud/demo-accounts.env`, readable only by root and the service).
4. Later updates: `sudo /opt/securecloud/deploy/update.sh`. Stop the VM from the portal when not
   demoing to stretch the student credit.

What `setup.sh` installs: K3s + Cilium + Hubble, RBAC and the admission policy, the workload
images, the API as a sandboxed systemd service (`securecloud-api`), Hubble relay and capture
services, testbed storefront forwards, and Caddy with an automatic HTTPS certificate. Public
mode uses secure `__Host-` cookies and refuses to seed any account password shorter than
16 characters. Logs: `journalctl -u securecloud-api -f`.

### Sleep when idle, wake on visit (optional)

`deploy/bin/idle-shutdown.sh` (systemd timer every 5 minutes) deallocates the VM after
`SECURECLOUD_IDLE_MINUTES` (default 30) without a real visitor, using the VM's managed identity.
Grant it with `az vm identity assign` and a *Virtual Machine Contributor* role assignment scoped to
the VM; without that the timer does nothing.

`deploy/wake/` is an Azure Function (Flex Consumption) used as the public entry point. It shows a
boot screen, starts the VM from the page's JavaScript (so link previews and crawlers do not wake
it), and redirects once the shops answer. Its managed identity needs the same role on the VM, and
it reads `SC_SUBSCRIPTION`, `SC_RESOURCE_GROUP`, `SC_VM` and `SC_SITE` from its app settings.

## Local lab (Windows + WSL)

## 1. Cluster (WSL Ubuntu with systemd, or any Linux host)

```bash
sudo backend/manifests/lab/install-k3s-cilium.sh      # K3s + Cilium + Hubble Relay; pins cluster DNS
sudo k3s kubectl apply -f backend/manifests/lab/securecloud-rbac.yaml
backend/manifests/lab/create-backend-kubeconfig.sh runtime/securecloud.kubeconfig
```

`securecloud-rbac.yaml` creates the backend service account with least-privilege rights and a
`ValidatingAdmissionPolicy` that only lets it delete namespaces labelled `securecloud.io/kind=shop`
(self-service shops). System and testbed namespaces can never be deleted by the backend.

`pin-cluster-dns.sh` (run by the installer) gives K3s its own resolver file. Without it, WSL's
generated `/etc/resolv.conf` breaks pod DNS.

## 2. Workload images

The shop template and platform services use a locally built image:

```bash
cd backend/reference_apps
docker build -t docker.io/securecloud/reference-api:0.6.0 .
docker save docker.io/securecloud/reference-api:0.6.0 | sudo k3s ctr images import -
```

## 3. Demo accounts (gitignored, never committed)

Create `runtime/demo-accounts.env` with `ROLE=email:password` lines (CUSTOMER, NORTHSTAR_OWNER,
BLOOM_OWNER, PROVIDER). `start.ps1` seeds them on every start.

## 4. Start everything (Windows host)

```powershell
./start.ps1          # starts the lab, Hubble capture, API (:8000) and portal (:4174)
./start.ps1 -Stop    # stops services left by a -KeepRunning session
```

Closing the window, pressing Ctrl+C or killing the launcher stops every service it started
(a watchdog handles hard kills).

| Setting | Default | Meaning |
|---|---|---|
| `SECURECLOUD_SHOP_QUOTA` | 5 | Live shops the single-node lab may run (testbed shops included) |
| `SECURECLOUD_MARKETPLACE` | 1 | Mall mode: shops, provider console, attack testbed |

## 5. Surfaces

| URL | Who | What |
|---|---|---|
| `/` | everyone | Story landing page and live list of shops |
| `/start` | signed-in users | Create a shop from the template (self-service tenant) |
| `/{shop}/shop`, `/{shop}/admin` | shoppers, owners and staff | Storefront and shop admin |
| `/admin` | provider | Console: overview graph, alerts, shops, traffic, workloads, network policy |
| `/lab` | provider | Attack testbed and evaluation scorecard (kept separate from the console) |

## 6. Verify

```bash
.venv/Scripts/python -m pytest backend/tests -q
cd frontend && npm run build && npx vitest run
```

Live checks: run a testbed scenario and confirm drops appear in Hubble, then create a shop at
`/start` and confirm its namespace has `default-deny`, restricted Pod Security and a quota
(`Shops → Posture` in the console shows the same checks).

## Limitations

Containers stand in for virtual machines. The lab is a single node with synthetic attack
traffic. Namespace isolation is soft multi-tenancy and does not replace a cloud provider's own
tenant isolation. The "Reach the Kubernetes API" scenario can report inconclusive when Hubble
attributes the flow to the API-server identity; it is never counted as blocked without an
observed drop.
