"""Prepare a bounded, hardened Online Boutique manifest for local feasibility tests."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import yaml


UPSTREAM_VERSION = "v0.10.3"
UPSTREAM_COMMIT = "cd1cb59f6fce3e2ccf08be7cea743e3784932d73"
UPSTREAM_MANIFEST_SHA256 = "681b58e962f9fb1fa49854483f98ac52b01f53bae6fad7868dc758abcff86354"
DEFAULT_NAMESPACE = "sc-retail-spike"

IMAGE_DIGESTS = {
    "busybox:1.36.1": "docker.io/library/busybox@sha256:73aaf090f3d85aa34ee199857f03fa3a95c8ede2ffd4cc2cdb5b94e566b11662",
    "redis:7.2.5-alpine": "docker.io/library/redis@sha256:6aaf3f5e6bc8a592fbfe2cccf19eb36d27c39d12dab4f4b01556b7449e7b1f44",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/adservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/adservice@sha256:ff1a059bb8f1226b77b42a9102344cfc4b669a04696eb44aeed3db8ae2b04e9e",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/cartservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/cartservice@sha256:598efe871d0251cbd35729972acb23c0723cb7aca451503ba10fb8116aecb958",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/checkoutservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/checkoutservice@sha256:6688da8718a92373cc149c8423936b342123060e86705804f9ffbc421bd2ae8f",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/currencyservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/currencyservice@sha256:f7d6e530d10ecbf8a10408bd6e114ed6d7670130bb28d22309bb66fcb99ebdb9",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/emailservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/emailservice@sha256:59558f8e668e4edec7b40a928c2368696474a8da85ef912e278f8abb3200ecbe",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/frontend:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/frontend@sha256:83f44050fc5ea5999ea04a940e687d7bd5ad357fcf6e6f5944e5e32de006bbdb",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/loadgenerator:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/loadgenerator@sha256:49fc8f2312d72c6e61b697d378601cfc53f30af3cdbbc7c105759c0024d0c456",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/paymentservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/paymentservice@sha256:d95567da89a5e7c3c819f1b742c12a3bf4a2ad35af0ddbcbd06eb908252e67d9",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/productcatalogservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/productcatalogservice@sha256:c358001d318f6bec85f49119653f19bbc235a0a323e45c936dc74460701fd129",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/recommendationservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/recommendationservice@sha256:2f3eae327b743160033cec8662362e2190f9aa9a04a1ace1bd05f19106ed4bd3",
    "us-central1-docker.pkg.dev/google-samples/microservices-demo/shippingservice:v0.10.3": "us-central1-docker.pkg.dev/google-samples/microservices-demo/shippingservice@sha256:b0125be448f9eb042214fec6eebda79a900a1a4c307f8e1bdb56f35e403969dd",
}


def _namespace(namespace: str, tenant_id: str, purpose: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "securecloud",
                "securecloud.io/purpose": purpose,
                "securecloud.io/tenant": sha256(tenant_id.encode()).hexdigest()[:16],
                "pod-security.kubernetes.io/enforce": "restricted",
                "pod-security.kubernetes.io/enforce-version": "latest",
                "pod-security.kubernetes.io/audit": "restricted",
                "pod-security.kubernetes.io/warn": "restricted",
            },
            "annotations": {"securecloud.io/tenant-id": tenant_id},
        },
    }


def _controls(namespace: str) -> list[dict]:
    return [
        {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": "retail-spike-quota", "namespace": namespace},
            "spec": {
                "hard": {
                    "requests.cpu": "2",
                    "requests.memory": "2Gi",
                    "limits.cpu": "4",
                    "limits.memory": "4Gi",
                    "pods": "20",
                }
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "default-deny", "namespace": namespace},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "allow-tenant-internal", "namespace": namespace},
            "spec": {
                "podSelector": {},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespace}}}]}],
                "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespace}}}]}],
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "allow-dns", "namespace": namespace},
            "spec": {
                "podSelector": {},
                "policyTypes": ["Egress"],
                "egress": [{
                    "to": [{
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                        "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                    }],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                }],
            },
        },
    ]


def prepare_documents(
    source: Path,
    namespace: str = DEFAULT_NAMESPACE,
    *,
    tenant_id: str = "retail-spike",
    purpose: str = "retail-feasibility",
    workload_ids: dict[str, str] | None = None,
    workload_templates: dict[str, str] | None = None,
) -> tuple[list[dict], dict]:
    source_bytes = source.read_bytes()
    if sha256(source_bytes).hexdigest() != UPSTREAM_MANIFEST_SHA256:
        raise ValueError("Online Boutique manifest does not match the pinned v0.10.3 source")
    upstream = [item for item in yaml.safe_load_all(source_bytes) if item]
    documents: list[dict] = [_namespace(namespace, tenant_id, purpose)]
    deployments: list[str] = []
    images: set[str] = set()

    for original in upstream:
        item = deepcopy(original)
        metadata = item.setdefault("metadata", {})
        if item.get("kind") == "ServiceAccount":
            continue
        if item.get("kind") == "Service" and metadata.get("name") == "frontend-external":
            continue
        metadata["namespace"] = namespace
        metadata.setdefault("labels", {}).update({
            "app.kubernetes.io/managed-by": "securecloud",
            "securecloud.io/tenant-id": tenant_id,
        })
        if item.get("kind") == "Deployment":
            name = metadata["name"]
            deployments.append(name)
            pod = item["spec"]["template"]
            pod["metadata"].setdefault("labels", {}).update({
                "app.kubernetes.io/managed-by": "securecloud",
                "securecloud.io/tenant-id": tenant_id,
                "securecloud.io/workload": name,
            })
            pod["metadata"].pop("annotations", None)
            pod_spec = pod["spec"]
            pod_spec["automountServiceAccountToken"] = False
            pod_spec.pop("serviceAccountName", None)
            pod_spec.setdefault("securityContext", {})["seccompProfile"] = {"type": "RuntimeDefault"}
            workload_id = (workload_ids or {}).get(name, name)
            pod["metadata"]["labels"]["securecloud.io/workload"] = sha256(
                workload_id.encode()
            ).hexdigest()[:16]
            if workload_templates and name in workload_templates:
                pod["metadata"]["labels"]["securecloud.io/template"] = (
                    workload_templates[name]
                )
            pod["metadata"].setdefault("annotations", {}).update({
                "securecloud.io/workload-id": workload_id,
                "securecloud.io/tenant-id": tenant_id,
            })
            for container in pod_spec.get("initContainers", []):
                container.setdefault("resources", {
                    "requests": {"cpu": "10m", "memory": "16Mi"},
                    "limits": {"cpu": "50m", "memory": "32Mi"},
                })
            for container in [*pod_spec.get("initContainers", []), *pod_spec.get("containers", [])]:
                if container["image"] == "redis:alpine":
                    container["image"] = "redis:7.2.5-alpine"
                elif container["image"] == "busybox:latest":
                    container["image"] = "busybox:1.36.1"
                try:
                    container["image"] = IMAGE_DIGESTS[container["image"]]
                except KeyError as error:
                    raise ValueError(
                        f"Online Boutique image is not pinned: {container['image']}"
                    ) from error
                images.add(container["image"])
        documents.append(item)

    documents.extend(_controls(namespace))
    summary = {
        "upstream_version": UPSTREAM_VERSION,
        "upstream_commit": UPSTREAM_COMMIT,
        "namespace": namespace,
        "deployments": sorted(deployments),
        "deployment_count": len(deployments),
        "images": sorted(images),
        "external_service_removed": True,
    }
    return documents, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    arguments = parser.parse_args()
    documents, summary = prepare_documents(arguments.source, arguments.namespace)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
