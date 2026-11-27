#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this verifier as root." >&2
  exit 1
fi

if [[ "$#" -eq 1 ]]; then
  exec >"$1" 2>&1
fi

export KUBECONFIG="/etc/rancher/k3s/k3s.yaml"

echo "== services =="
systemctl is-active k3s

echo "== versions =="
k3s --version
helm version --short
helm list --namespace kube-system

echo "== nodes =="
k3s kubectl wait node --all --for=condition=Ready --timeout=60s
k3s kubectl get nodes -o wide

echo "== cilium and hubble =="
k3s kubectl get daemonset/cilium \
  deployment/cilium-operator \
  deployment/hubble-relay \
  --namespace kube-system
k3s kubectl get pods --namespace kube-system -o wide

if ! k3s kubectl rollout status daemonset/cilium --namespace kube-system --timeout=90s \
  || ! k3s kubectl rollout status deployment/cilium-operator --namespace kube-system --timeout=90s \
  || ! k3s kubectl rollout status deployment/hubble-relay --namespace kube-system --timeout=90s; then
  echo "== failed rollout diagnostics =="
  k3s kubectl get events --namespace kube-system --sort-by=.lastTimestamp
  for selector in k8s-app=cilium io.cilium/app=operator k8s-app=hubble-relay; do
    k3s kubectl describe pods --namespace kube-system --selector "$selector" || true
    k3s kubectl logs --namespace kube-system --selector "$selector" --all-containers --tail=120 || true
    k3s kubectl logs --namespace kube-system --selector "$selector" --all-containers --previous --tail=120 || true
  done
  exit 1
fi

echo "== hubble exporter =="
k3s kubectl exec --namespace kube-system daemonset/cilium -- \
  sh -c 'test -f /var/run/cilium/hubble/events.log && wc -c /var/run/cilium/hubble/events.log'

echo "== api readiness =="
k3s kubectl get --raw=/readyz
