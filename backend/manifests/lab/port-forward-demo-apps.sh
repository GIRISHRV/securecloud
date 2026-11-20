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
  [[ -n "$retail_pid" ]] && kill "$retail_pid" 2>/dev/null || true
  [[ -n "$vendor_pid" ]] && kill "$vendor_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

forward_forever "$retail_namespace" frontend 8094:80 &
retail_pid=$!
forward_forever "$vendor_namespace" vendor-web 8095:80 &
vendor_pid=$!

wait "$retail_pid" "$vendor_pid"
