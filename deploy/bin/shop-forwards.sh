#!/usr/bin/env bash
# Loopback port-forwards for the two testbed storefronts (Northstar :8094, Bloom :8095).
# Self-service shops need none: the API reaches them through the Kubernetes service proxy.
set -euo pipefail
ns() { k3s kubectl get namespace -l "securecloud.io/purpose=$1" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true; }
northstar="$(ns northstar-shop-stack)"; bloom="$(ns bloom-shop-stack)"
if [[ -z "${northstar}" || -z "${bloom}" ]]; then echo "testbed shops not provisioned yet" >&2; exit 1; fi
exec "$(dirname "${BASH_SOURCE[0]}")/../../backend/manifests/lab/port-forward-demo-apps.sh" "${northstar}" "${bloom}" northstar-web bloom-web
