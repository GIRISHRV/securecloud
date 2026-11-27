#!/usr/bin/env bash
set -euo pipefail

readonly CILIUM_VERSION="1.20.4"
readonly K3S_VERSION="v1.36.6+k3s1"
readonly KUBECONFIG_PATH="/etc/rancher/k3s/k3s.yaml"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

if [[ "$(ps -p 1 -o comm=)" != "systemd" ]]; then
  echo "K3s requires systemd in this WSL distribution." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --yes --no-install-recommends ca-certificates curl

# Must run before K3s starts so kubelet never hands pods the WSL resolver.
"$(dirname "${BASH_SOURCE[0]}")/pin-cluster-dns.sh"

if command -v k3s >/dev/null 2>&1; then
  installed_k3s_version="$(k3s --version | awk 'NR == 1 {print $3}')"
  if [[ "${installed_k3s_version}" != "${K3S_VERSION}" ]]; then
    echo "Expected K3s ${K3S_VERSION}, found ${installed_k3s_version}." >&2
    echo "Recreate the empty lab before rerunning this installer." >&2
    exit 1
  fi
else
  curl --fail --silent --show-error --location https://get.k3s.io \
    | INSTALL_K3S_VERSION="${K3S_VERSION}" \
      INSTALL_K3S_EXEC="server --flannel-backend=none --disable-network-policy --disable=traefik --disable=servicelb" \
      sh -
fi

export KUBECONFIG="${KUBECONFIG_PATH}"
systemctl enable --now k3s

for _ in $(seq 1 60); do
  if k3s kubectl get --raw=/readyz >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if ! k3s kubectl get --raw=/readyz >/dev/null 2>&1; then
  echo "K3s API did not become ready." >&2
  systemctl status k3s --no-pager >&2 || true
  exit 1
fi

if ! command -v helm >/dev/null 2>&1; then
  curl --fail --silent --show-error --location \
    https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \
    --output /tmp/get-helm-3
  chmod 0700 /tmp/get-helm-3
  /tmp/get-helm-3
  rm -f /tmp/get-helm-3
fi

if helm status cilium --namespace kube-system >/dev/null 2>&1; then
  helm upgrade cilium oci://quay.io/cilium/charts/cilium \
    --version "${CILIUM_VERSION}" \
    --namespace kube-system \
    --reuse-values \
    --set operator.replicas=1 \
    --set hubble.relay.enabled=true \
    --set hubble.export.static.enabled=true \
    --set hubble.export.static.filePath=/var/run/cilium/hubble/events.log \
    --set hubble.export.static.fileMaxSizeMb=10 \
    --set hubble.export.static.fileMaxBackups=5 \
    --set 'hubble.export.static.fieldMask={time,uuid,source.namespace,source.pod_name,source.workloads,destination.namespace,destination.pod_name,destination.workloads,l4,node_name,verdict,drop_reason_desc}'
else
  helm install cilium oci://quay.io/cilium/charts/cilium \
    --version "${CILIUM_VERSION}" \
    --namespace kube-system \
    --set operator.replicas=1 \
    --set hubble.relay.enabled=true \
    --set hubble.export.static.enabled=true \
    --set hubble.export.static.filePath=/var/run/cilium/hubble/events.log \
    --set hubble.export.static.fileMaxSizeMb=10 \
    --set hubble.export.static.fileMaxBackups=5 \
    --set 'hubble.export.static.fieldMask={time,uuid,source.namespace,source.pod_name,source.workloads,destination.namespace,destination.pod_name,destination.workloads,l4,node_name,verdict,drop_reason_desc}'
fi

k3s kubectl rollout status daemonset/cilium \
  --namespace kube-system \
  --timeout=5m
k3s kubectl rollout status deployment/cilium-operator \
  --namespace kube-system \
  --timeout=5m
k3s kubectl rollout status deployment/hubble-relay \
  --namespace kube-system \
  --timeout=5m

echo "SecureCloud lab cluster is ready."
k3s kubectl get nodes -o wide
k3s kubectl get pods --namespace kube-system -o wide
