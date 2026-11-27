#!/usr/bin/env bash
# SecureCloud one-line installer for a fresh Ubuntu 24.04 VM.
#
#   curl -fsSL https://raw.githubusercontent.com/GIRISHRV/securecloud/main/deploy/install.sh | sudo bash
#
# Optional: pass your own domain (for example an Azure DNS label):
#   curl -fsSL .../install.sh | sudo bash -s -- securecloud-demo.centralindia.cloudapp.azure.com
#
# Without a domain it uses <public-ip>.sslip.io, a free DNS name that points at this VM, so HTTPS
# works with no DNS setup. Re-running it updates the code and redeploys (data is kept).
set -euo pipefail

REPO="https://github.com/GIRISHRV/securecloud.git"
APP=/opt/securecloud
DOMAIN="${1:-${SECURECLOUD_DOMAIN:-}}"

[[ "${EUID}" -eq 0 ]] || { echo "Run with sudo: curl -fsSL <url> | sudo bash" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git curl ca-certificates

if [[ -d "${APP}/.git" ]]; then
  # The server copy has no local edits; follow GitHub exactly, even if history was rewritten.
  git -C "${APP}" fetch --force origin main
  git -C "${APP}" reset --hard origin/main
else
  git clone "${REPO}" "${APP}"
fi

if [[ -z "${DOMAIN}" ]]; then
  # Azure instance metadata first (never leaves the VM), then a public echo service as a fallback.
  IP="$(curl -fsS -H Metadata:true --max-time 3 \
    "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text" 2>/dev/null || true)"
  [[ "${IP}" =~ ^[0-9]+(\.[0-9]+){3}$ ]] || IP="$(curl -fsS --max-time 5 https://api.ipify.org)"
  [[ "${IP}" =~ ^[0-9]+(\.[0-9]+){3}$ ]] || { echo "Could not find this VM's public IP; pass a domain as the first argument." >&2; exit 1; }
  DOMAIN="${IP//./-}.sslip.io"
  echo "Using free domain: ${DOMAIN}"
fi

exec bash "${APP}/deploy/setup.sh" "${DOMAIN}"
