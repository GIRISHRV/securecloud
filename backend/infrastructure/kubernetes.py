"""Kubernetes implementation for bounded SecureCloud catalog workloads."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import secrets
from typing import Mapping

from backend.catalog import stack_definition
from backend.experiments.retail_spike import prepare_documents

from .base import (
    ContainmentObservation,
    InfrastructureConflict,
    InfrastructureError,
    InfrastructurePending,
    InfrastructureUnavailable,
    StackObservation,
    StackRequest,
    WorkloadObservation,
    WorkloadRequest,
)


FIELD_MANAGER = "securecloud-control-plane"
APPLY_CONTENT_TYPE = "application/apply-patch+yaml"


@dataclass(frozen=True)
class Template:
    port: int
    cpu_request: str
    cpu_limit: str
    memory_request: str
    memory_limit: str


TEMPLATES = {
    "web": Template(80, "50m", "250m", "64Mi", "128Mi"),
    "api": Template(8080, "100m", "500m", "128Mi", "256Mi"),
    "database": Template(5432, "100m", "500m", "256Mi", "512Mi"),
}

REFERENCE_PROFILES = {"college", "hospital"}
REFERENCE_SECRET = "securecloud-reference-db"


def tenant_namespace(tenant_id: str) -> str:
    return f"sc-{sha256(tenant_id.encode()).hexdigest()[:12]}"


def workload_label(workload_id: str) -> str:
    return sha256(workload_id.encode()).hexdigest()[:16]


class KubernetesInfrastructure:
    def __init__(
        self,
        kubeconfig: Path | None = None,
        context: str | None = None,
        api_server: str | None = None,
        retail_manifest: Path | None = None,
    ):
        try:
            from kubernetes import client, config
            from kubernetes.client.rest import ApiException
        except ImportError as exc:  # pragma: no cover - exercised by deployment packaging
            raise RuntimeError("Install backend requirements to enable Kubernetes") from exc

        self.client = client
        self.ApiException = ApiException
        if kubeconfig:
            config.load_kube_config(config_file=str(kubeconfig), context=context)
        else:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config(context=context)
        if api_server:
            configuration = client.Configuration.get_default_copy()
            configuration.host = api_server
            configuration.verify_ssl = api_server.startswith("https://")
            client.Configuration.set_default(configuration)
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self.networking = client.NetworkingV1Api()
        self.custom = client.CustomObjectsApi()
        self.version = client.VersionApi()
        self.retail_manifest = retail_manifest

    def health(self) -> dict:
        try:
            version = self.version.get_code()
            return {"connected": True, "provider": "kubernetes", "version": version.git_version}
        except Exception as exc:
            raise self._translate(exc) from exc

    def reconcile(self, action: str, workload: WorkloadRequest) -> WorkloadObservation:
        try:
            if action == "deploy":
                return self._deploy(workload)
            if action == "stop":
                return self._stop(workload)
            if action == "delete":
                return self._delete(workload)
            raise ValueError(f"Unsupported action: {action}")
        except (InfrastructureError, ValueError):
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    def reconcile_stack(
        self,
        action: str,
        stack: StackRequest,
        components: Mapping[str, WorkloadRequest],
    ) -> StackObservation:
        try:
            if action != "deploy":
                raise ValueError(f"Unsupported stack action: {action}")
            if stack.stack_id != "retail-stack":
                raise ValueError("Stack has no Kubernetes reconciler")
            return self._deploy_retail_stack(stack, components)
        except (InfrastructureError, ValueError):
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    def _deploy_retail_stack(
        self,
        stack: StackRequest,
        components: Mapping[str, WorkloadRequest],
    ) -> StackObservation:
        if self.retail_manifest is None:
            raise InfrastructureUnavailable("Retail manifest is not configured")
        definition = stack_definition(stack.stack_id)
        if definition is None:
            raise InfrastructureError("Stack definition is unavailable")
        expected = {service.id for service in definition.services}
        if set(components) != expected:
            raise InfrastructureError("Stack component inventory does not match catalog")

        namespace = tenant_namespace(stack.tenant_id)
        self._ensure_namespace(namespace, stack.tenant_id)
        documents, _ = prepare_documents(
            self.retail_manifest,
            namespace,
            tenant_id=stack.tenant_id,
            purpose="retail-stack",
            workload_ids={name: request.id for name, request in components.items()},
            workload_templates={
                service.id: service.template for service in definition.services
            },
        )
        deployments = {}
        for document in documents:
            kind = document["kind"]
            if kind == "Namespace":
                self._apply_namespace(namespace, document)
                continue
            name = document["metadata"]["name"]
            if kind == "ResourceQuota":
                self._apply(
                    self.core.patch_namespaced_resource_quota,
                    name,
                    namespace,
                    document,
                )
            elif kind == "NetworkPolicy":
                self._apply(
                    self.networking.patch_namespaced_network_policy,
                    name,
                    namespace,
                    document,
                )
            elif kind == "Service":
                self._apply(
                    self.core.patch_namespaced_service,
                    name,
                    namespace,
                    document,
                )
            elif kind == "Deployment":
                deployments[name] = self._apply(
                    self.apps.patch_namespaced_deployment,
                    name,
                    namespace,
                    document,
                )
            else:
                raise InfrastructureError(f"Unsupported retail manifest kind: {kind}")

        observations = {
            name: WorkloadObservation(
                "running" if self._deployment_ready(deployment) else "pending",
                deployment.metadata.uid,
                deployment.metadata.resource_version,
            )
            for name, deployment in deployments.items()
        }
        result = StackObservation(
            "running"
            if all(item.state == "running" for item in observations.values())
            else "pending",
            observations,
        )
        if result.state != "running":
            raise InfrastructurePending(
                "Retail stack has not become fully available", result
            )
        return result

    def _apply_namespace(self, name: str, body: dict):
        return self.core.patch_namespace(
            name=name,
            body=body,
            field_manager=FIELD_MANAGER,
            force=True,
            _content_type=APPLY_CONTENT_TYPE,
        )

    def reconcile_quarantine(
        self, workload: WorkloadRequest, enabled: bool
    ) -> ContainmentObservation:
        """Reconcile a Cilium deny policy; deny rules override additive allows."""
        namespace = tenant_namespace(workload.tenant_id)
        name = f"quarantine-{workload_label(workload.id)}"
        try:
            if enabled:
                body = self._quarantine_policy(workload, namespace, name)
                self.custom.patch_namespaced_custom_object(
                    group="cilium.io",
                    version="v2",
                    namespace=namespace,
                    plural="ciliumnetworkpolicies",
                    name=name,
                    body=body,
                    field_manager=FIELD_MANAGER,
                    force=True,
                    _content_type=APPLY_CONTENT_TYPE,
                )
                observed = self.custom.get_namespaced_custom_object(
                    group="cilium.io",
                    version="v2",
                    namespace=namespace,
                    plural="ciliumnetworkpolicies",
                    name=name,
                )
                metadata = observed.get("metadata", {})
                spec = observed.get("spec", {})
                expected_selector = {
                    "matchLabels": {"securecloud.io/workload": workload_label(workload.id)}
                }
                if (
                    spec.get("endpointSelector") != expected_selector
                    or not spec.get("ingressDeny")
                    or not spec.get("egressDeny")
                ):
                    raise InfrastructurePending("Cilium quarantine policy is not fully observed")
                return ContainmentObservation(
                    "quarantined",
                    metadata.get("uid"),
                    metadata.get("resourceVersion"),
                )

            try:
                current = self.custom.get_namespaced_custom_object(
                    group="cilium.io",
                    version="v2",
                    namespace=namespace,
                    plural="ciliumnetworkpolicies",
                    name=name,
                )
            except self.ApiException as exc:
                if exc.status == 404:
                    self._ensure_namespace_controls(namespace)
                    return ContainmentObservation("restored", None, None)
                raise
            metadata = current.get("metadata", {})
            options = self.client.V1DeleteOptions(
                preconditions=self.client.V1Preconditions(
                    uid=metadata.get("uid"),
                    resource_version=metadata.get("resourceVersion"),
                )
            )
            self.custom.delete_namespaced_custom_object(
                group="cilium.io",
                version="v2",
                namespace=namespace,
                plural="ciliumnetworkpolicies",
                name=name,
                body=options,
            )
            try:
                self.custom.get_namespaced_custom_object(
                    group="cilium.io",
                    version="v2",
                    namespace=namespace,
                    plural="ciliumnetworkpolicies",
                    name=name,
                )
            except self.ApiException as exc:
                if exc.status == 404:
                    self._ensure_namespace_controls(namespace)
                    return ContainmentObservation("restored", None, None)
                raise
            raise InfrastructurePending("Cilium quarantine policy deletion is still in progress")
        except (InfrastructureError, ValueError):
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    @staticmethod
    def _quarantine_policy(workload: WorkloadRequest, namespace: str, name: str) -> dict:
        labels = {"securecloud.io/workload": workload_label(workload.id)}
        return {
            "apiVersion": "cilium.io/v2",
            "kind": "CiliumNetworkPolicy",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "annotations": {
                    "securecloud.io/workload-id": workload.id,
                    "securecloud.io/tenant-id": workload.tenant_id,
                },
            },
            "spec": {
                "endpointSelector": {"matchLabels": labels},
                "ingressDeny": [{"fromEntities": ["all"]}],
                "egressDeny": [{"toEntities": ["all"]}],
            },
        }

    def _apply(self, method, name: str, namespace: str, body: dict):
        return method(
            name=name,
            namespace=namespace,
            body=body,
            field_manager=FIELD_MANAGER,
            force=True,
            _content_type=APPLY_CONTENT_TYPE,
        )

    def _deploy(self, workload: WorkloadRequest) -> WorkloadObservation:
        template = TEMPLATES[workload.template]
        namespace = tenant_namespace(workload.tenant_id)
        self._ensure_namespace(namespace, workload.tenant_id)
        self._ensure_namespace_controls(namespace)
        labels = {
            "app.kubernetes.io/managed-by": "securecloud",
            "securecloud.io/workload": workload_label(workload.id),
            "securecloud.io/template": workload.template,
        }
        annotations = {
            "securecloud.io/workload-id": workload.id,
            "securecloud.io/tenant-id": workload.tenant_id,
        }
        reference_profile = workload.tenant_id if workload.tenant_id in REFERENCE_PROFILES else None
        if reference_profile and workload.template in {"api", "database"}:
            self._ensure_reference_secret(namespace, annotations)
        if reference_profile and workload.template == "database":
            self._ensure_database_storage(namespace, workload.name, labels, annotations)
        container, pod_security_context, volumes = self._container_spec(
            workload, template, reference_profile
        )
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": workload.name, "namespace": namespace, "labels": labels, "annotations": annotations},
            "spec": {
                "replicas": 1,
                "minReadySeconds": 5,
                "progressDeadlineSeconds": 120,
                "selector": {"matchLabels": {"securecloud.io/workload": labels["securecloud.io/workload"]}},
                "template": {
                    "metadata": {"labels": labels, "annotations": annotations},
                    "spec": {
                        "automountServiceAccountToken": False,
                        "securityContext": pod_security_context,
                        "containers": [container],
                        **({"volumes": volumes} if volumes else {}),
                    },
                },
            },
        }
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": workload.name, "namespace": namespace, "labels": labels, "annotations": annotations},
            "spec": {
                "selector": {"securecloud.io/workload": labels["securecloud.io/workload"]},
                "ports": [{"name": "service", "port": template.port, "targetPort": "service", "protocol": "TCP"}],
                "type": "ClusterIP",
            },
        }
        result = self._apply(self.apps.patch_namespaced_deployment, workload.name, namespace, deployment)
        self._apply(self.core.patch_namespaced_service, workload.name, namespace, service)
        ready = self._deployment_ready(result)
        if not ready:
            raise InfrastructurePending(
                "Deployment has not become available",
                WorkloadObservation("pending", result.metadata.uid, result.metadata.resource_version),
            )
        return WorkloadObservation("running", result.metadata.uid, result.metadata.resource_version)

    @staticmethod
    def _deployment_ready(deployment) -> bool:
        desired = deployment.spec.replicas or 0
        status = deployment.status
        return (
            desired > 0
            and status.observed_generation == deployment.metadata.generation
            and (status.updated_replicas or 0) == desired
            and (status.available_replicas or 0) == desired
            and (status.replicas or 0) == desired
            and (status.unavailable_replicas or 0) == 0
        )

    def _container_spec(
        self,
        workload: WorkloadRequest,
        template: Template,
        reference_profile: str | None,
    ) -> tuple[dict, dict, list[dict]]:
        security_context = {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        }
        pod_security_context = {
            "runAsNonRoot": True,
            "runAsUser": 10001,
            "runAsGroup": 10001,
            "fsGroup": 10001,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        container = {
            "name": "workload",
            "image": "registry.k8s.io/e2e-test-images/agnhost:2.53",
            "imagePullPolicy": "IfNotPresent",
            "args": ["netexec", f"--http-port={template.port}"],
            "ports": [{"name": "service", "containerPort": template.port, "protocol": "TCP"}],
            "readinessProbe": {"httpGet": {"path": "/healthz", "port": "service"}, "initialDelaySeconds": 1, "periodSeconds": 2},
            "livenessProbe": {"httpGet": {"path": "/healthz", "port": "service"}, "initialDelaySeconds": 5, "periodSeconds": 10},
            "resources": {
                "requests": {"cpu": template.cpu_request, "memory": template.memory_request},
                "limits": {"cpu": template.cpu_limit, "memory": template.memory_limit},
            },
            "securityContext": security_context,
        }
        if not reference_profile:
            return container, pod_security_context, []

        if workload.template == "web":
            container.update({
                "image": "docker.io/securecloud/reference-web:0.2.0",
                "args": [],
                "env": [{"name": "API_UPSTREAM", "value": f"{reference_profile}-api"}],
                "ports": [{"name": "service", "containerPort": 8080, "protocol": "TCP"}],
                "readinessProbe": {"httpGet": {"path": "/", "port": "service"}, "initialDelaySeconds": 1, "periodSeconds": 3},
                "livenessProbe": {"httpGet": {"path": "/", "port": "service"}, "initialDelaySeconds": 5, "periodSeconds": 10},
                "volumeMounts": [
                    {"name": "nginx-config", "mountPath": "/etc/nginx/conf.d"},
                    {"name": "tmp", "mountPath": "/tmp"},
                ],
            })
            pod_security_context.update({"runAsUser": 101, "runAsGroup": 101, "fsGroup": 101})
            return container, pod_security_context, [
                {"name": "nginx-config", "emptyDir": {}},
                {"name": "tmp", "emptyDir": {}},
            ]

        secret_password = {"secretKeyRef": {"name": REFERENCE_SECRET, "key": "password"}}
        if workload.template == "api":
            container.update({
                "image": "docker.io/securecloud/reference-api:0.2.0",
                "args": [],
                "env": [
                    {"name": "APP_PROFILE", "value": reference_profile},
                    {"name": "PGHOST", "value": f"{reference_profile}-database"},
                    {"name": "PGDATABASE", "value": "securecloud"},
                    {"name": "PGUSER", "value": "securecloud"},
                    {"name": "PGPASSWORD", "valueFrom": secret_password},
                ],
                "readinessProbe": {"httpGet": {"path": "/health", "port": "service"}, "initialDelaySeconds": 2, "periodSeconds": 3},
                "livenessProbe": {"httpGet": {"path": "/health", "port": "service"}, "initialDelaySeconds": 8, "periodSeconds": 10},
            })
            return container, pod_security_context, []

        pod_security_context.update({"runAsUser": 70, "runAsGroup": 70, "fsGroup": 70})
        container.update({
            "image": "docker.io/library/postgres:17.7-alpine3.23",
            "args": [],
            "env": [
                {"name": "POSTGRES_DB", "value": "securecloud"},
                {"name": "POSTGRES_USER", "value": "securecloud"},
                {"name": "POSTGRES_PASSWORD", "valueFrom": secret_password},
                {"name": "PGDATA", "value": "/var/lib/postgresql/data/pgdata"},
            ],
            "startupProbe": {"exec": {"command": ["pg_isready", "-U", "securecloud", "-d", "securecloud"]}, "periodSeconds": 3, "failureThreshold": 40},
            "readinessProbe": {"exec": {"command": ["pg_isready", "-U", "securecloud", "-d", "securecloud"]}, "periodSeconds": 3},
            "livenessProbe": {"exec": {"command": ["pg_isready", "-U", "securecloud", "-d", "securecloud"]}, "periodSeconds": 10, "failureThreshold": 3},
            "volumeMounts": [
                {"name": "data", "mountPath": "/var/lib/postgresql/data"},
                {"name": "run", "mountPath": "/var/run/postgresql"},
                {"name": "tmp", "mountPath": "/tmp"},
            ],
        })
        volumes = [
            {"name": "data", "persistentVolumeClaim": {"claimName": f"{workload.name}-data"}},
            {"name": "run", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ]
        return container, pod_security_context, volumes

    def _ensure_reference_secret(self, namespace: str, annotations: dict) -> None:
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": REFERENCE_SECRET, "namespace": namespace, "annotations": annotations},
            "type": "Opaque",
            "stringData": {"password": secrets.token_urlsafe(32)},
        }
        try:
            self.core.create_namespaced_secret(namespace=namespace, body=body)
        except self.ApiException as exc:
            if exc.status != 409:
                raise

    def _ensure_database_storage(self, namespace: str, name: str, labels: dict, annotations: dict) -> None:
        body = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": f"{name}-data", "namespace": namespace, "labels": labels, "annotations": annotations},
            "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}},
        }
        self._apply(self.core.patch_namespaced_persistent_volume_claim, f"{name}-data", namespace, body)

    def _stop(self, workload: WorkloadRequest) -> WorkloadObservation:
        namespace = tenant_namespace(workload.tenant_id)
        current = self.apps.read_namespaced_deployment(workload.name, namespace)
        self._check_preconditions(workload, current)
        body = {"metadata": {"resourceVersion": current.metadata.resource_version}, "spec": {"replicas": 0}}
        result = self.apps.patch_namespaced_deployment(workload.name, namespace, body)
        if (result.status.replicas or 0) != 0:
            raise InfrastructurePending(
                "Workload pods are still terminating",
                WorkloadObservation("stopping", result.metadata.uid, result.metadata.resource_version),
            )
        return WorkloadObservation("stopped", result.metadata.uid, result.metadata.resource_version)

    def _delete(self, workload: WorkloadRequest) -> WorkloadObservation:
        namespace = tenant_namespace(workload.tenant_id)
        try:
            current = self.apps.read_namespaced_deployment(workload.name, namespace)
        except self.ApiException as exc:
            if exc.status == 404:
                return WorkloadObservation("deleted", None, None)
            raise
        if current.metadata.deletion_timestamp is not None:
            raise InfrastructurePending(
                "Deletion is still in progress",
                WorkloadObservation("deleting", current.metadata.uid, current.metadata.resource_version),
            )
        self._check_preconditions(workload, current)
        preconditions = self.client.V1Preconditions(uid=current.metadata.uid, resource_version=current.metadata.resource_version)
        options = self.client.V1DeleteOptions(propagation_policy="Foreground", preconditions=preconditions)
        self.apps.delete_namespaced_deployment(workload.name, namespace, body=options)
        try:
            self.core.delete_namespaced_service(workload.name, namespace)
        except self.ApiException as exc:
            if exc.status != 404:
                raise
        raise InfrastructurePending(
            "Deletion requested; waiting for confirmation",
            WorkloadObservation("deleting", current.metadata.uid, current.metadata.resource_version),
        )

    def _check_preconditions(self, workload: WorkloadRequest, resource):
        if not workload.kubernetes_uid or not workload.kubernetes_version:
            raise InfrastructureConflict("Missing previously observed Kubernetes identity")
        if workload.kubernetes_uid != resource.metadata.uid:
            raise InfrastructureConflict("Kubernetes UID changed")

    def _ensure_namespace(self, namespace: str, tenant_id: str):
        body = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace,
                "labels": {
                    "app.kubernetes.io/managed-by": "securecloud",
                    "securecloud.io/tenant": sha256(tenant_id.encode()).hexdigest()[:16],
                    "pod-security.kubernetes.io/enforce": "restricted",
                    "pod-security.kubernetes.io/enforce-version": "latest",
                    "pod-security.kubernetes.io/audit": "restricted",
                    "pod-security.kubernetes.io/warn": "restricted",
                },
                "annotations": {"securecloud.io/tenant-id": tenant_id},
            },
        }
        self.core.patch_namespace(
            name=namespace,
            body=body,
            field_manager=FIELD_MANAGER,
            force=True,
            _content_type=APPLY_CONTENT_TYPE,
        )

    def _ensure_namespace_controls(self, namespace: str):
        quota = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": "securecloud-quota", "namespace": namespace},
            "spec": {"hard": {"pods": "12", "requests.cpu": "4", "requests.memory": "4Gi", "limits.cpu": "8", "limits.memory": "8Gi"}},
        }
        self._apply(self.core.patch_namespaced_resource_quota, "securecloud-quota", namespace, quota)
        for policy in self._policies(namespace):
            self._apply(self.networking.patch_namespaced_network_policy, policy["metadata"]["name"], namespace, policy)

    @staticmethod
    def _policies(namespace: str) -> list[dict]:
        def policy(name: str, spec: dict) -> dict:
            return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": name, "namespace": namespace}, "spec": spec}

        return [
            policy("default-deny", {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}),
            policy("allow-dns", {
                "podSelector": {}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}], "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}],
            }),
            policy("web-to-api", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "web"}}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"podSelector": {"matchLabels": {"securecloud.io/template": "api"}}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
            }),
            policy("api-from-web", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "api"}}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"podSelector": {"matchLabels": {"securecloud.io/template": "web"}}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
            }),
            policy("api-to-database", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "api"}}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"podSelector": {"matchLabels": {"securecloud.io/template": "database"}}}], "ports": [{"protocol": "TCP", "port": 5432}]}],
            }),
            policy("database-from-api", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "database"}}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"podSelector": {"matchLabels": {"securecloud.io/template": "api"}}}], "ports": [{"protocol": "TCP", "port": 5432}]}],
            }),
        ]

    def _translate(self, exc: Exception) -> InfrastructureError:
        if isinstance(exc, self.ApiException):
            if exc.status == 409:
                return InfrastructureConflict("Kubernetes resource version conflict")
            if exc.status in {0, 429, 500, 502, 503, 504}:
                return InfrastructureUnavailable("Kubernetes API is unavailable")
            return InfrastructureError(f"Kubernetes API rejected the operation ({exc.status})")
        return InfrastructureUnavailable("Kubernetes state could not be observed")
