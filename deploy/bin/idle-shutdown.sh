#!/usr/bin/env bash
# Deallocate this Azure VM after SECURECLOUD_IDLE_MINUTES without a real visitor (0 disables).
# A "visitor" is an /api/ request in Caddy's access log that is not the wake front door's own
# health check; scanners probing random paths do not count. Uses the VM's managed identity.
set -euo pipefail
IDLE="${SECURECLOUD_IDLE_MINUTES:-30}"
LOG=/var/log/caddy/access.log
[[ "${IDLE}" =~ ^[0-9]+$ && "${IDLE}" -gt 0 ]] || exit 0
up=$(cut -d. -f1 /proc/uptime)
(( up > 20 * 60 )) || exit 0   # give a fresh boot time to receive its visitor

last=$(python3 - "${LOG}" <<'PY'
import json, sys
last = 0.0
try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            r = e.get("request", {})
            ua = " ".join(r.get("headers", {}).get("User-Agent", []))
            if r.get("uri", "").startswith("/api/") and "securecloud-wake" not in ua:
                last = max(last, float(e.get("ts", 0)))
except FileNotFoundError:
    pass
print(int(last))
PY
)
now=$(date +%s); boot=$(( now - up )); (( last > boot )) || last=${boot}
# An install or update counts as activity, so a fresh access log never triggers an instant shutdown.
reset=$(stat -c %Y /var/lib/securecloud/idle-reset 2>/dev/null || echo 0); (( last > reset )) || last=${reset}
idle_for=$(( (now - last) / 60 ))
if (( idle_for < IDLE )); then exit 0; fi

echo "No visitors for ${idle_for} min (limit ${IDLE}); deallocating this VM."
imds() { curl -fsS -H Metadata:true --max-time 5 "http://169.254.169.254/metadata/$1"; }
token=$(imds "identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/" | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
id=$(imds "instance/compute/resourceId?api-version=2021-02-01&format=text")
curl -fsS -X POST -H "Authorization: Bearer ${token}" -H "Content-Length: 0" \
  "https://management.azure.com${id}/deallocate?api-version=2024-07-01"
