#!/usr/bin/env bash
# Pull the latest code and redeploy (keeps data, accounts and the cluster).
set -euo pipefail
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
git -C "${APP}" pull --ff-only
exec "${APP}/deploy/setup.sh" "$(sed -n 's#^SECURECLOUD_ORIGIN=https://##p' /etc/securecloud/securecloud.env)"
