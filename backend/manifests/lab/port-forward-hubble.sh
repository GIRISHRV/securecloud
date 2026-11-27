#!/usr/bin/env bash
set -euo pipefail

# Expose Hubble Relay only on the host loopback interface for local evidence capture.
# Retry forever: right after boot the service can still point at a pod that is being replaced
# ("pod not found"), and a relay restart drops the forward; both must heal without a relaunch.
child=""
trap '[[ -n "$child" ]] && kill "$child" 2>/dev/null; exit 0' INT TERM EXIT
while true; do
  k3s kubectl -n kube-system port-forward service/hubble-relay 4245:80 --address 127.0.0.1 &
  child=$!
  wait "$child" || true
  child=""
  sleep 2
done
