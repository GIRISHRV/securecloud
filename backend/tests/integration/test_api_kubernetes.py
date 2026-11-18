import os
from pathlib import Path
import secrets
import time

import pytest
from fastapi.testclient import TestClient

from backend.api import Settings, create_app


KUBECONFIG = os.environ.get("SECURECLOUD_KUBECONFIG")
pytestmark = pytest.mark.skipif(not KUBECONFIG, reason="real cluster kubeconfig not supplied")


def wait_for_operation(client: TestClient, tenant_id: str, operation_id: str, timeout: float = 90.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/tenants/{tenant_id}/operations/{operation_id}")
        assert response.status_code == 200, response.text
        operation = response.json()
        if operation["status"] in {"succeeded", "failed", "inconclusive"}:
            return operation
        time.sleep(1)
    raise AssertionError("Operation did not reach a terminal state")


def test_authenticated_api_reconciles_real_workload(tmp_path):
    settings = Settings(
        database=tmp_path / "integration.sqlite",
        origin="http://testserver",
        secure_cookie=False,
        infrastructure="kubernetes",
        kubeconfig=Path(KUBECONFIG),
    )
    app = create_app(settings)
    password = secrets.token_urlsafe(24)
    app.state.store.create_user("integration-admin", password, administrator=True)

    with TestClient(app) as client:
        client.headers["Origin"] = settings.origin
        login = client.post("/api/auth/login", json={"username": "integration-admin", "password": password})
        assert login.status_code == 200, login.text
        client.headers["X-CSRF-Token"] = login.json()["csrf"]

        health = client.get("/api/health").json()["infrastructure"]
        assert health["connected"] is True
        assert health["provider"] == "kubernetes"

        tenant = client.post("/api/tenants", json={"name": "Integration tenant"}).json()
        deploy = client.post(
            f"/api/tenants/{tenant['id']}/workloads",
            json={"name": "portal-web", "template": "web"},
            headers={"Idempotency-Key": "integration-deploy"},
        )
        assert deploy.status_code == 202, deploy.text
        deployed = wait_for_operation(client, tenant["id"], deploy.json()["id"])
        assert deployed["status"] == "succeeded", deployed

        workload = client.get(f"/api/tenants/{tenant['id']}/workloads").json()[0]
        assert workload["observed"] == "running"
        assert workload["kubernetes_uid"]
        assert workload["kubernetes_version"]

        stop = client.post(
            f"/api/tenants/{tenant['id']}/workloads/{workload['id']}/stop",
            json={"confirmation": workload["name"], "expected_version": workload["version"]},
            headers={"Idempotency-Key": "integration-stop"},
        )
        assert stop.status_code == 202, stop.text
        stopped = wait_for_operation(client, tenant["id"], stop.json()["id"])
        assert stopped["status"] == "succeeded", stopped

        workload = client.get(f"/api/tenants/{tenant['id']}/workloads").json()[0]
        assert workload["observed"] == "stopped"
        delete = client.post(
            f"/api/tenants/{tenant['id']}/workloads/{workload['id']}/delete",
            json={"confirmation": workload["name"], "expected_version": workload["version"]},
            headers={"Idempotency-Key": "integration-delete"},
        )
        assert delete.status_code == 202, delete.text
        deleted = wait_for_operation(client, tenant["id"], delete.json()["id"])
        assert deleted["status"] == "succeeded", deleted
        assert client.get(f"/api/tenants/{tenant['id']}/workloads").json() == []
