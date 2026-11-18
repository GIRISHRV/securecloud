#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this credential bootstrap as root." >&2
  exit 1
fi
if [[ "$#" -ne 1 ]]; then
  echo "Usage: $0 OUTPUT_KUBECONFIG" >&2
  exit 1
fi

readonly OUTPUT_PATH="$1"
readonly MANIFEST_PATH="/mnt/e/GIRISH/Projects/actualfyp/backend/manifests/lab/securecloud-rbac.yaml"
readonly NAMESPACE="securecloud-system"
readonly SECRET_NAME="securecloud-backend-token"

export KUBECONFIG="/etc/rancher/k3s/k3s.yaml"
umask 077
mkdir -p "$(dirname "${OUTPUT_PATH}")"
k3s kubectl apply -f "${MANIFEST_PATH}" >/dev/null

for _ in $(seq 1 30); do
  if [[ -n "$(k3s kubectl get secret "${SECRET_NAME}" --namespace "${NAMESPACE}" -o jsonpath='{.data.token}' 2>/dev/null)" ]]; then
    break
  fi
  sleep 1
done

token_data="$(k3s kubectl get secret "${SECRET_NAME}" --namespace "${NAMESPACE}" -o jsonpath='{.data.token}')"
if [[ -z "${token_data}" ]]; then
  echo "Service-account token material was not issued." >&2
  exit 1
fi

token="$(printf '%s' "${token_data}" | base64 --decode)"
k3s kubectl config set-cluster securecloud-lab \
  --kubeconfig="${OUTPUT_PATH}" \
  --server=https://127.0.0.1:6443 \
  --certificate-authority=/var/lib/rancher/k3s/server/tls/server-ca.crt \
  --embed-certs=true >/dev/null
k3s kubectl config set-credentials securecloud-backend \
  --kubeconfig="${OUTPUT_PATH}" \
  --token="${token}" >/dev/null
k3s kubectl config set-context securecloud-lab \
  --kubeconfig="${OUTPUT_PATH}" \
  --cluster=securecloud-lab \
  --user=securecloud-backend >/dev/null
k3s kubectl config use-context securecloud-lab --kubeconfig="${OUTPUT_PATH}" >/dev/null
chmod 0600 "${OUTPUT_PATH}"
unset token

KUBECONFIG="${OUTPUT_PATH}" k3s kubectl auth can-i create deployments.apps --all-namespaces | grep -qx yes
KUBECONFIG="${OUTPUT_PATH}" k3s kubectl auth can-i create secrets --all-namespaces | grep -qx yes
KUBECONFIG="${OUTPUT_PATH}" k3s kubectl auth can-i get secrets --all-namespaces | grep -qx no
echo "SecureCloud backend kubeconfig created with restricted RBAC."
