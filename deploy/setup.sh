#!/usr/bin/env bash
# SecureCloud: Zero Trust Security Framework for Multi-Tenant Cloud Virtualisation
# One-command server setup for a single Ubuntu 24.04 VM (tested target: Azure B2s, 2 vCPU / 4 GB).
#
#   sudo git clone https://github.com/GIRISHRV/securecloud.git /opt/securecloud
#   sudo /opt/securecloud/deploy/setup.sh <public-domain>
#
# Safe to re-run: every step is idempotent. Demo account passwords are generated once, stored
# only on the server (root-only file), and printed at the end of the first run.
set -euo pipefail

DOMAIN="${1:?Usage: setup.sh <public domain, e.g. securecloud.centralindia.cloudapp.azure.com>}"
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA=/var/lib/securecloud
ETC=/etc/securecloud
NODE_VERSION=v22.21.1
HUBBLE_VERSION=v1.20.4
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

[[ "${EUID}" -eq 0 ]] || { echo "Run as root (sudo)." >&2; exit 1; }
[[ "${DOMAIN}" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] || { echo "That does not look like a domain name." >&2; exit 1; }

step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl git docker.io python3-venv python3-pip gnupg debian-keyring debian-archive-keyring apt-transport-https
systemctl enable --now docker

step "Network MTU ${MTU:-1400} (Azure drops full-size 1500-byte packets on this path; large TLS handshakes stall)"
IFACE="$(ip -o route get 1.1.1.1 | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')"
cat > /etc/systemd/system/securecloud-mtu.service <<EOF
[Unit]
Description=SecureCloud: clamp ${IFACE} MTU so large packets are not silently dropped
After=network-online.target
Wants=network-online.target
Before=k3s.service docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip link set ${IFACE} mtu ${MTU:-1400}

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
MTU_BEFORE="$(cat /sys/class/net/${IFACE}/mtu)"
systemctl enable --now securecloud-mtu
systemctl restart securecloud-mtu

step "Kubernetes (K3s) + Cilium + Hubble"
bash "${APP}/backend/manifests/lab/install-k3s-cilium.sh"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
if [[ "${MTU_BEFORE}" != "${MTU:-1400}" ]] && k3s kubectl -n kube-system get ds cilium >/dev/null 2>&1; then
  # Cilium reads the device MTU at start-up; restart it so pod routes use the new size.
  k3s kubectl -n kube-system rollout restart ds/cilium
  k3s kubectl -n kube-system rollout status ds/cilium --timeout=300s
fi
k3s kubectl apply -f "${APP}/backend/manifests/lab/securecloud-rbac.yaml"

step "Workload images (shop template, platform services, storefront)"
docker build --network host -t docker.io/securecloud/reference-api:0.6.0 "${APP}/backend/reference_apps"
docker build --network host -t docker.io/securecloud/reference-web:0.2.0 "${APP}/frontend/reference-app"
docker save docker.io/securecloud/reference-api:0.6.0 docker.io/securecloud/reference-web:0.2.0 | k3s ctr images import -

step "Service user, data directory and least-privilege kubeconfig"
id securecloud >/dev/null 2>&1 || useradd --system --home "${DATA}" --shell /usr/sbin/nologin securecloud
install -d -o securecloud -g securecloud -m 0750 "${DATA}" "${DATA}/media"
install -d -m 0750 -g securecloud "${ETC}"   # service group may enter; files inside stay 0640
bash "${APP}/backend/manifests/lab/create-backend-kubeconfig.sh" "${DATA}/securecloud.kubeconfig"
chown securecloud:securecloud "${DATA}/securecloud.kubeconfig"

step "Hubble CLI ${HUBBLE_VERSION}"
if ! /usr/local/bin/hubble version 2>/dev/null | grep -q "${HUBBLE_VERSION}"; then
  curl -fsSL -o /tmp/hubble.tgz "https://github.com/cilium/hubble/releases/download/${HUBBLE_VERSION}/hubble-linux-amd64.tar.gz"
  tar -xzf /tmp/hubble.tgz -C /usr/local/bin hubble && rm -f /tmp/hubble.tgz
fi

step "Python environment (CPU-only PyTorch)"
python3 -m venv "${APP}/.venv-server"
"${APP}/.venv-server/bin/pip" install -q --upgrade pip
"${APP}/.venv-server/bin/pip" install -q --index-url https://download.pytorch.org/whl/cpu "torch==2.15.0"
"${APP}/.venv-server/bin/pip" install -q -r "${APP}/backend/requirements.txt"

step "Node ${NODE_VERSION} and the portal build"
if ! /opt/node/bin/node --version 2>/dev/null | grep -q "${NODE_VERSION}"; then
  curl -fsSL -o /tmp/node.tar.xz "https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz"
  rm -rf /opt/node && mkdir -p /opt/node && tar -xJf /tmp/node.tar.xz -C /opt/node --strip-components=1 && rm -f /tmp/node.tar.xz
fi
( cd "${APP}/frontend" && PATH="/opt/node/bin:${PATH}" npm ci --no-audit --no-fund && PATH="/opt/node/bin:${PATH}" npm run build )

step "Configuration"
FIRST_ACCOUNTS=0
if [[ ! -f "${ETC}/demo-accounts.env" ]]; then
  FIRST_ACCOUNTS=1
  umask 077
  python3 - "${DOMAIN}" > "${ETC}/demo-accounts.env" <<'PY'
import secrets, sys
domain = sys.argv[1]
for role, user in (("PROVIDER", "provider"), ("NORTHSTAR_OWNER", "northstar"), ("BLOOM_OWNER", "bloom"), ("CUSTOMER", "customer")):
    print(f"{role}={user}@{domain}:{secrets.token_urlsafe(18)}")
PY
fi
if ! grep -q '^GUEST=' "${ETC}/demo-accounts.env"; then
  # Public reviewer login, shown on the home page on purpose: it cannot remove, pause or reconfigure shops.
  echo "GUEST=guest@${DOMAIN}:$(python3 -c 'import secrets; print(secrets.token_urlsafe(13))')" >> "${ETC}/demo-accounts.env"
fi
chmod 0640 "${ETC}/demo-accounts.env" && chgrp securecloud "${ETC}/demo-accounts.env"
cat > "${ETC}/securecloud.env" <<EOF
SECURECLOUD_DB=${DATA}/securecloud.sqlite
SECURECLOUD_RETAIL_DB=${DATA}/commerce.sqlite
SECURECLOUD_ORIGIN=https://${DOMAIN}
SECURECLOUD_SECURE_COOKIE=1
SECURECLOUD_PUBLIC=1
SECURECLOUD_INFRASTRUCTURE=kubernetes
SECURECLOUD_KUBECONFIG=${DATA}/securecloud.kubeconfig
SECURECLOUD_HUBBLE_EXPORT=${DATA}/hubble-current.jsonl
SECURECLOUD_SHOP_QUOTA=5
SECURECLOUD_FLOW_RETENTION_SECONDS=86400
SECURECLOUD_GUEST_LOGIN=$(sed -n 's/^GUEST=//p' "${ETC}/demo-accounts.env")
EOF
chmod 0640 "${ETC}/securecloud.env" && chgrp securecloud "${ETC}/securecloud.env"

step "Provision the mall (testbed shops and shared platform) and seed accounts"
run_as_app() { sudo -u securecloud --preserve-env=PYTHONPATH env $(grep -v '^#' "${ETC}/securecloud.env" | xargs) PYTHONPATH="${APP}" "$@"; }
( cd "${APP}" && run_as_app "${APP}/.venv-server/bin/python" -m backend.bootstrap_mall \
    --database "${DATA}/securecloud.sqlite" --kubeconfig "${DATA}/securecloud.kubeconfig" ) || echo "Provisioning continues in the background."
( cd "${APP}" && run_as_app "${APP}/.venv-server/bin/python" -m backend.retail_seed \
    --database "${DATA}/commerce.sqlite" --accounts "${ETC}/demo-accounts.env" )

step "Services"
for unit in "${APP}"/deploy/systemd/*.service; do
  sed "s#@APP@#${APP}#g; s#@DATA@#${DATA}#g; s#@ETC@#${ETC}#g" "${unit}" > "/etc/systemd/system/$(basename "${unit}")"
done
chmod +x "${APP}"/deploy/bin/*.sh "${APP}"/backend/manifests/lab/*.sh
systemctl daemon-reload
systemctl enable --now securecloud-hubble-relay securecloud-hubble-capture securecloud-shop-forwards securecloud-api
systemctl restart securecloud-api

step "Caddy (HTTPS with an automatic Let's Encrypt certificate)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi
sed "s#@DOMAIN@#${DOMAIN}#g; s#@APP@#${APP}#g" "${APP}/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

step "Done"
echo "SecureCloud is live at: https://${DOMAIN}"
echo "  provider console  https://${DOMAIN}/admin     attack testbed  https://${DOMAIN}/lab"
if [[ "${FIRST_ACCOUNTS}" == 1 ]]; then
  echo
  echo "Demo accounts (shown once; stored root/securecloud-only in ${ETC}/demo-accounts.env):"
  sed 's/^/  /' "${ETC}/demo-accounts.env"
fi
