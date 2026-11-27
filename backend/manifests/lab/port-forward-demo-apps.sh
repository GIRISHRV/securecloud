#!/usr/bin/env bash
set -euo pipefail

retail_namespace="${1:?retail namespace is required}"
vendor_namespace="${2:?vendor namespace is required}"

retail_pid=""
vendor_pid=""
forward_forever() {
  local namespace="$1"
  local service="$2"
  local mapping="$3"
  while true; do
    k3s kubectl -n "$namespace" port-forward "service/$service" "$mapping" \
      --address 127.0.0.1 || true
    sleep 1
  done
}
cleanup() {
  # Stop the kubectl each forward loop is running, then the loop itself (now in its 1s sleep).
  # Killing only the loop would orphan its kubectl port-forward, which keeps holding the port.
  for pid in "$retail_pid" "$vendor_pid"; do
    [[ -n "$pid" ]] || continue
    pkill -P "$pid" 2>/dev/null || true
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

forward_forever "$retail_namespace" "${3:-frontend}" 8094:80 &
retail_pid=$!
forward_forever "$vendor_namespace" "${4:-vendor-web}" 8095:80 &
vendor_pid=$!

wait "$retail_pid" "$vendor_pid"
