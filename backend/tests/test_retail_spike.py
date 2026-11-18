from pathlib import Path

import pytest
import yaml

from backend.experiments.retail_spike import DEFAULT_NAMESPACE, prepare_documents


SOURCE = Path("runtime/vendor-spikes/online-boutique/release/kubernetes-manifests.yaml")


def test_retail_spike_manifest_is_bounded_and_hardened():
    if not SOURCE.exists():
        pytest.skip("pinned Online Boutique source is not present")
    documents, summary = prepare_documents(SOURCE)
    assert summary["deployment_count"] == 12
    assert summary["external_service_removed"] is True
    assert not any(
        item["kind"] == "Service" and item["metadata"]["name"] == "frontend-external"
        for item in documents
    )
    deployments = [item for item in documents if item["kind"] == "Deployment"]
    for deployment in deployments:
        pod = deployment["spec"]["template"]
        assert deployment["metadata"]["namespace"] == DEFAULT_NAMESPACE
        assert pod["spec"]["automountServiceAccountToken"] is False
        assert pod["spec"]["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
        assert len(pod["metadata"]["labels"]["securecloud.io/workload"]) == 16
        assert pod["metadata"]["annotations"]["securecloud.io/workload-id"] == deployment["metadata"]["name"]
        assert all(container.get("resources") for container in pod["spec"].get("initContainers", []))
    serialized = yaml.safe_dump_all(documents)
    assert "redis:alpine" not in serialized
    assert "busybox:latest" not in serialized
    assert all("@sha256:" in image for image in summary["images"])
    assert not any(item["kind"] == "ServiceAccount" for item in documents)


def test_retail_stack_uses_tenant_and_stable_component_identity():
    if not SOURCE.exists():
        pytest.skip("pinned Online Boutique source is not present")
    workload_ids = {"frontend": "workload-frontend"}
    documents, _ = prepare_documents(
        SOURCE,
        "sc-tenant",
        tenant_id="tenant-1",
        purpose="retail-stack",
        workload_ids=workload_ids,
        workload_templates={"frontend": "web"},
    )
    namespace = next(item for item in documents if item["kind"] == "Namespace")
    frontend = next(
        item
        for item in documents
        if item["kind"] == "Deployment"
        and item["metadata"]["name"] == "frontend"
    )
    pod = frontend["spec"]["template"]

    assert namespace["metadata"]["annotations"]["securecloud.io/tenant-id"] == "tenant-1"
    assert namespace["metadata"]["labels"]["securecloud.io/purpose"] == "retail-stack"
    assert pod["metadata"]["annotations"] == {
        "securecloud.io/workload-id": "workload-frontend",
        "securecloud.io/tenant-id": "tenant-1",
    }
    assert pod["metadata"]["labels"]["securecloud.io/template"] == "web"
    assert "serviceAccountName" not in pod["spec"]


def test_retail_spike_rejects_unpinned_source():
    source = Path(__file__)
    with pytest.raises(ValueError, match="does not match"):
        prepare_documents(source)
