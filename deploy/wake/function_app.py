"""SecureCloud front door: wakes the demo VM on the first visit and shows a boot screen.

Runs as an always-on Azure Function (consumption plan) with a system-assigned managed identity
that may only start and read the one VM (Virtual Machine Contributor scoped to that VM).
The page starts the VM with a POST from JavaScript, so link previews and most crawlers that
only fetch the URL do not wake it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import azure.functions as func

SUB, RG, VM = os.environ["SC_SUBSCRIPTION"], os.environ["SC_RESOURCE_GROUP"], os.environ["SC_VM"]
SITE = os.environ["SC_SITE"].rstrip("/")
ARM = f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Compute/virtualMachines/{VM}"
PAGE = (Path(__file__).parent / "boot.html").read_text(encoding="utf-8")
_token: dict = {"value": "", "expires": 0.0}

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def token() -> str:
    if _token["expires"] - time.time() > 300:
        return _token["value"]
    url = f"{os.environ['IDENTITY_ENDPOINT']}?resource=https://management.azure.com/&api-version=2019-08-01"
    req = urllib.request.Request(url, headers={"X-IDENTITY-HEADER": os.environ["IDENTITY_HEADER"]})
    with urllib.request.urlopen(req, timeout=10) as response:
        body = json.load(response)
    _token.update(value=body["access_token"], expires=float(body["expires_on"]))
    return _token["value"]


def arm(method: str, path: str = "") -> dict:
    req = urllib.request.Request(f"{ARM}{path}?api-version=2024-07-01", method=method, data=b"" if method == "POST" else None,
                                 headers={"Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def power() -> str:
    statuses = arm("GET", "/instanceView").get("statuses", [])
    return next((s["code"].split("/", 1)[1] for s in statuses if s["code"].startswith("PowerState/")), "unknown")


def site_ready() -> bool:
    req = urllib.request.Request(f"{SITE}/api/mall/shops", headers={"User-Agent": "securecloud-wake"})
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def as_json(data: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(data), status_code=status, mimetype="application/json",
                             headers={"Cache-Control": "no-store"})


def status() -> func.HttpResponse:
    state = power()
    return as_json({"power": state, "ready": state == "running" and site_ready(), "site": SITE})


@app.route(route="api/wake", methods=["POST"])
def wake(req: func.HttpRequest) -> func.HttpResponse:
    state = power()
    if state in ("deallocated", "stopped", "deallocating", "stopping"):
        arm("POST", "/start")  # idempotent; Azure queues it behind a stop in progress
        state = "starting"
    return as_json({"power": state}, 202)


@app.route(route="{*path}", methods=["GET"])
def page(req: func.HttpRequest) -> func.HttpResponse:
    path = req.route_params.get("path") or ""
    if path == "api/status":  # the catch-all route takes precedence over literal GET routes, so dispatch here
        return status()
    if power() == "running" and site_ready():  # awake: go straight to the same page on the site
        return func.HttpResponse(status_code=302, headers={"Location": f"{SITE}/{path}", "Cache-Control": "no-store"})
    return func.HttpResponse(PAGE.replace("{{SITE}}", SITE).replace("{{PATH}}", "/" + path),
                             mimetype="text/html", headers={"Cache-Control": "no-store"})
