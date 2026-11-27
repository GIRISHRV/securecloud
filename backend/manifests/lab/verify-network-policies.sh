#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this verifier as root." >&2
  exit 1
fi
if [[ "$#" -lt 2 || "$#" -gt 3 ]]; then
  echo "Usage: $0 COLLEGE_NAMESPACE HOSPITAL_NAMESPACE [OUTPUT_FILE]" >&2
  exit 1
fi

readonly COLLEGE_NAMESPACE="$1"
readonly HOSPITAL_NAMESPACE="$2"
if [[ "$#" -eq 3 ]]; then
  exec >"$3" 2>&1
fi

export KUBECONFIG="/etc/rancher/k3s/k3s.yaml"

pod_for_template() {
  local namespace="$1"
  local template="$2"
  k3s kubectl get pods \
    --namespace "${namespace}" \
    --selector "securecloud.io/template=${template}" \
    --field-selector status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}'
}

probe() {
  local expectation="$1"
  local namespace="$2"
  local template="$3"
  local destination="$4"
  local label="$5"
  local pod
  local result
  local probe_status
  pod="$(pod_for_template "${namespace}" "${template}")"
  set +e
  result="$(k3s kubectl exec --namespace "${namespace}" "${pod}" -- \
    /agnhost connect --timeout=3s "${destination}" 2>&1)"
  probe_status=$?
  set -e

  if [[ "${expectation}" == "allowed" ]]; then
    if [[ "${probe_status}" -ne 0 ]] || grep -Eq '^(TIMEOUT|DNS|REFUSED|OTHER|UNKNOWN)' <<<"${result}"; then
      echo "FAIL allowed ${label}: ${result}"
      return 1
    fi
    echo "PASS allowed ${label}"
    return 0
  fi

  if [[ "${probe_status}" -ne 0 ]] && grep -Eq '^(TIMEOUT|REFUSED|OTHER)' <<<"${result}"; then
    denial_reason="$(printf '%s\n' "${result}" | head -n 1)"
    echo "PASS denied ${label}: ${denial_reason}"
    return 0
  fi
  echo "FAIL denied ${label}: connection succeeded"
  return 1
}

probe allowed "${COLLEGE_NAMESPACE}" web "college-api:8080" "college web -> college API:8080"
probe allowed "${COLLEGE_NAMESPACE}" api "college-database:5432" "college API -> college database:5432"
probe denied "${COLLEGE_NAMESPACE}" web "college-database:5432" "college web -> college database:5432"
probe denied "${COLLEGE_NAMESPACE}" web "hospital-api.${HOSPITAL_NAMESPACE}.svc.cluster.local:8080" "college web -> hospital API:8080"
