import os
from pathlib import Path
import time

import pytest

from backend.infrastructure import InfrastructurePending, WorkloadRequest
from backend.infrastructure.kubernetes import KubernetesInfrastructure


KUBECONFIG = os.environ.get("SECURECLOUD_KUBECONFIG")
pytestmark = pytest.mark.skipif(not KUBECONFIG, reason="real cluster kubeconfig not supplied")


def wait_for(infrastructure, action: str, request: WorkloadRequest, timeout: float = 90.0):
    deadline = time.monotonic() + timeout
    current = request
    while time.monotonic() < deadline:
        try:
            return infrastructure.reconcile(action, current)
        except InfrastructurePending as exc:
            if exc.observation is not None:
                current = WorkloadRequest(
                    current.id,
                    current.tenant_id,
                    current.name,
                    current.template,
                    exc.observation.uid,
                    exc.observation.resource_version,
                )
            time.sleep(2)
    raise AssertionError(f"Timed out waiting for {action}")


def test_real_deploy_stop_delete_lifecycle():
    infrastructure = KubernetesInfrastructure(Path(KUBECONFIG))
    request = WorkloadRequest(
        id="integration-web",
        tenant_id="integration-tenant",
        name="integration-web",
        template="web",
    )

    running = wait_for(infrastructure, "deploy", request)
    assert running.state == "running"
    assert running.uid and running.resource_version

    observed = WorkloadRequest(
        request.id,
        request.tenant_id,
        request.name,
        request.template,
        running.uid,
        running.resource_version,
    )
    stopped = wait_for(infrastructure, "stop", observed)
    assert stopped.state == "stopped"

    stopped_request = WorkloadRequest(
        request.id,
        request.tenant_id,
        request.name,
        request.template,
        stopped.uid,
        stopped.resource_version,
    )
    deleted = wait_for(infrastructure, "delete", stopped_request)
    assert deleted.state == "deleted"
