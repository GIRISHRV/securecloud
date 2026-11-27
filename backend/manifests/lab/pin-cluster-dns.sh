#!/usr/bin/env bash
# Give K3s its own resolv.conf instead of the WSL-generated /etc/resolv.conf.
#
# WSL points /etc/resolv.conf at its DNS proxy (10.255.255.254), which answers the WSL host but is
# unreachable from pod network namespaces, and it can copy a junk search domain from a Windows
# adapter (seen: "eth2.20@domain"). Kubelet copies both into every pod, so each lookup walks into
# a search step that CoreDNS forwards upstream and times out; glibc then reports EAI_AGAIN and
# every in-cluster name fails. A fixed upstream with no search line keeps cluster DNS working.
set -euo pipefail

readonly CONFIG_DIR="/etc/rancher/k3s"
readonly RESOLV_PATH="${CONFIG_DIR}/resolv.conf"
readonly CONFIG_PATH="${CONFIG_DIR}/config.yaml"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

mkdir -p "${CONFIG_DIR}"
desired_resolv=$'nameserver 1.1.1.1\nnameserver 8.8.8.8\n'
changed=0

if [[ ! -f "${RESOLV_PATH}" ]] || [[ "$(cat "${RESOLV_PATH}")"$'\n' != "${desired_resolv}" ]]; then
  printf '%s' "${desired_resolv}" > "${RESOLV_PATH}"
  changed=1
fi

if ! grep -qs "^resolv-conf: ${RESOLV_PATH}\$" "${CONFIG_PATH}"; then
  touch "${CONFIG_PATH}"
  sed -i '/^resolv-conf:/d' "${CONFIG_PATH}"
  echo "resolv-conf: ${RESOLV_PATH}" >> "${CONFIG_PATH}"
  changed=1
fi

if [[ "${changed}" -eq 1 ]]; then
  echo "K3s DNS pinned to ${RESOLV_PATH}; restart k3s and recreate pods to apply."
else
  echo "K3s DNS already pinned to ${RESOLV_PATH}."
fi
