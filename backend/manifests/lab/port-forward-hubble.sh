#!/usr/bin/env bash
set -euo pipefail

# Expose Hubble Relay only on the host loopback interface for local evidence capture.
exec k3s kubectl -n kube-system port-forward service/hubble-relay 4245:80 \
  --address 127.0.0.1
