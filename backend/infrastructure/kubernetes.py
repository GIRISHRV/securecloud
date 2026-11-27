"""Kubernetes implementation for bounded SecureCloud catalog workloads."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import secrets
from typing import Mapping

from backend.catalog import LEGACY_SHOP_STACKS, PLATFORM_PROFILES, PLATFORM_TENANT_ID, PLUGIN_PROFILES, SHOP_STACKS, is_shop_stack, stack_definition
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
SHOP_PROFILES = {"northstar", "bloom", "shop", "shipfast", "orderids", "payments", "email"}
SHOP_IMAGE = "docker.io/securecloud/reference-api:0.6.0"  # 0.6.0 adds the generic "shop" profile
NOT_PLUGIN = {"key": "securecloud.io/role", "operator": "NotIn", "values": ["plugin"]}
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

    def _running_pod(self, namespace: str, workload_id: str):
        try:
            pods = self.core.list_namespaced_pod(
                namespace,
                label_selector=f"securecloud.io/workload={workload_label(workload_id)}",
                field_selector="status.phase=Running",
            ).items
        except Exception as exc:
            raise self._translate(exc) from exc
        ready = [
            pod for pod in pods
            if pod.metadata.deletion_timestamp is None
            and all(status.ready for status in (pod.status.container_statuses or []))
        ]
        if not ready:
            raise InfrastructureUnavailable("No ready pod for the selected lab workload")
        return ready[0]

    def workload_pod_ip(self, namespace: str, workload_id: str) -> str:
        pod = self._running_pod(namespace, workload_id)
        if not pod.status.pod_ip:
            raise InfrastructureUnavailable("Lab workload pod has no IP yet")
        return pod.status.pod_ip

    def restart_workload(self, namespace: str, workload_id: str, deployment: str, timeout: float = 90.0):
        """Replace a lab workload's pod (like `kubectl rollout restart`); returns (old, new, seconds)."""
        import time as _time
        old = self._running_pod(namespace, workload_id).metadata.name
        started = _time.time()
        body = {"spec": {"template": {"metadata": {"annotations": {"securecloud.io/restarted-at": str(int(started))}}}}}
        try:
            self.apps.patch_namespaced_deployment(deployment, namespace, body)
        except Exception as exc:
            raise self._translate(exc) from exc
        while _time.time() - started < timeout:
            _time.sleep(1.0)
            try:
                pod = self._running_pod(namespace, workload_id)
            except InfrastructureError:
                continue
            if pod.metadata.name != old:
                return old, pod.metadata.name, _time.time() - started
        raise InfrastructurePending("The replacement pod did not become ready in time")

    def exec_in_workload(self, namespace: str, workload_id: str, argv: list[str], timeout: float = 90.0) -> str:
        """Run a server-built lab command in a workload's first container (lab harness only)."""
        from kubernetes.stream import stream

        pod = self._running_pod(namespace, workload_id)
        try:
            return stream(
                self.core.connect_get_namespaced_pod_exec,
                pod.metadata.name,
                namespace,
                container=pod.spec.containers[0].name,
                command=argv,
                stderr=False,
                stdin=False,
                stdout=True,
                tty=False,
                _request_timeout=timeout,
            )
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
            if stack.stack_id == "retail-stack":
                return self._deploy_retail_stack(stack, components)
            if stack.stack_id == "facilities-vendor-stack":
                return self._deploy_facilities_vendor_stack(stack, components)
            if stack.stack_id in SHOP_STACKS:
                return self._deploy_shop_stack(stack, components)
            raise ValueError("Stack has no Kubernetes reconciler")
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
        service_ports = {service.id: service.port for service in definition.services}
        documents, _ = prepare_documents(
            self.retail_manifest,
            namespace,
            tenant_id=stack.tenant_id,
            purpose="retail-stack",
            workload_ids={name: request.id for name, request in components.items()},
            workload_templates={
                service.id: service.template for service in definition.services
            },
            service_intents=tuple(
                (service.id, dependency, service_ports[dependency])
                for service in definition.services
                for dependency in service.dependencies
                if service_ports.get(dependency) is not None
            ),
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

    def _deploy_shop_stack(self, stack: StackRequest, components: Mapping[str, WorkloadRequest]) -> StackObservation:
        definition = stack_definition(stack.stack_id)
        if definition is None or set(components) != {service.id for service in definition.services}:
            raise InfrastructureError("Stack component inventory does not match catalog")
        profile, prefix = SHOP_STACKS[stack.stack_id]
        observations = {
            service.id: self._apply_profile_workload(
                components[service.id],
                reference_profile=PLUGIN_PROFILES.get(service.id) or PLATFORM_PROFILES.get(service.id) or profile,
                api_upstream=f"{prefix}-api",
                database_upstream=f"{prefix}-database",
                namespace_purpose=stack.stack_id,
                role="plugin" if service.id in PLUGIN_PROFILES else "platform" if service.id in PLATFORM_PROFILES else None,
            )
            for service in definition.services
        }
        result = StackObservation(
            "running" if all(item.state == "running" for item in observations.values()) else "pending",
            observations,
        )
        if result.state != "running":
            raise InfrastructurePending("Shop stack has not become fully available", result)
        return result

    def _deploy_facilities_vendor_stack(
        self,
        stack: StackRequest,
        components: Mapping[str, WorkloadRequest],
    ) -> StackObservation:
        definition = stack_definition(stack.stack_id)
        if definition is None:
            raise InfrastructureError("Stack definition is unavailable")
        expected = {service.id for service in definition.services}
        if set(components) != expected:
            raise InfrastructureError("Stack component inventory does not match catalog")

        observations = {
            service.id: self._apply_profile_workload(
                components[service.id],
                reference_profile="facilities-vendor",
                api_upstream="vendor-api",
                database_upstream="vendor-database",
                namespace_purpose="facilities-vendor-stack",
            )
            for service in definition.services
        }
        result = StackObservation(
            "running"
            if all(item.state == "running" for item in observations.values())
            else "pending",
            observations,
        )
        if result.state != "running":
            raise InfrastructurePending(
                "Facilities vendor stack has not become fully available", result
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
                    self._restart_deployment_after_restore(
                        workload,
                        namespace,
                        None,
                    )
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
                    self._restart_deployment_after_restore(
                        workload,
                        namespace,
                        metadata.get("uid"),
                    )
                    return ContainmentObservation("restored", None, None)
                raise
            raise InfrastructurePending("Cilium quarantine policy deletion is still in progress")
        except (InfrastructureError, ValueError):
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    def _restart_deployment_after_restore(
        self,
        workload: WorkloadRequest,
        namespace: str,
        policy_uid: str | None,
    ) -> None:
        """Replace a pod that may have failed while its DNS was quarantined."""
        current = self.apps.read_namespaced_deployment(workload.name, namespace)
        self._check_preconditions(workload, current)
        marker = policy_uid or "policy-absent"
        body = {
            "metadata": {"resourceVersion": current.metadata.resource_version},
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "securecloud.io/restored-from-policy": marker,
                        }
                    }
                }
            },
        }
        self.apps.patch_namespaced_deployment(workload.name, namespace, body)

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
                # Deny every pod in every namespace and everything outside the node.
                # Deny rules win over allow rules, so "all" would also block the
                # kubelet's health probes and crash-loop the quarantined workload,
                # destroying its runtime state. Only the local node's host identity
                # (kubelet liveness/readiness probes) may still connect inbound. kube-apiserver
                # is not denied by entity: on single-node K3s it shares the host identity.
                "ingressDeny": [
                    {"fromEndpoints": [{"matchExpressions": [
                        {"key": "k8s:io.kubernetes.pod.namespace", "operator": "Exists"},
                    ]}]},
                    {"fromEntities": ["world", "remote-node", "ingress", "init", "unmanaged"]},
                ],
                "ingress": [{"fromEntities": ["host"]}],
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
        reference_profile = (
            workload.tenant_id
            if workload.tenant_id in REFERENCE_PROFILES
            else None
        )
        result = self._apply_profile_workload(
            workload,
            reference_profile=reference_profile,
        )
        if result.state != "running":
            raise InfrastructurePending(
                "Deployment has not become available",
                result,
            )
        return result

    def _apply_profile_workload(
        self,
        workload: WorkloadRequest,
        *,
        reference_profile: str | None,
        api_upstream: str | None = None,
        database_upstream: str | None = None,
        namespace_purpose: str | None = None,
        role: str | None = None,
    ) -> WorkloadObservation:
        template = TEMPLATES[workload.template]
        namespace = tenant_namespace(workload.tenant_id)
        self._ensure_namespace(
            namespace,
            workload.tenant_id,
            purpose=namespace_purpose,
        )
        self._ensure_namespace_controls(namespace)
        labels = {
            "app.kubernetes.io/managed-by": "securecloud",
            "securecloud.io/workload": workload_label(workload.id),
            "securecloud.io/template": workload.template,
        }
        if role:
            labels["securecloud.io/role"] = role
        annotations = {
            "securecloud.io/workload-id": workload.id,
            "securecloud.io/tenant-id": workload.tenant_id,
        }
        if reference_profile and workload.template in {"api", "database"}:
            self._ensure_reference_secret(namespace, annotations)
        if reference_profile and workload.template == "database":
            self._ensure_database_storage(namespace, workload.name, labels, annotations)
        container, pod_security_context, volumes = self._container_spec(
            workload,
            template,
            reference_profile,
            api_upstream=api_upstream,
            database_upstream=database_upstream,
            role=role,
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
        return WorkloadObservation(
            "running" if ready else "pending",
            result.metadata.uid,
            result.metadata.resource_version,
        )

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
        *,
        api_upstream: str | None = None,
        database_upstream: str | None = None,
        role: str | None = None,
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
                "env": [{
                    "name": "API_UPSTREAM",
                    "value": api_upstream or f"{reference_profile}-api",
                }],
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
                "image": (
                    SHOP_IMAGE
                    if reference_profile in SHOP_PROFILES
                    else "docker.io/securecloud/reference-api:0.3.0"
                    if reference_profile == "facilities-vendor"
                    else "docker.io/securecloud/reference-api:0.2.0"
                ),
                "args": [],
                "env": [
                    {"name": "APP_PROFILE", "value": reference_profile},
                    {
                        "name": "PGHOST",
                        "value": database_upstream or f"{reference_profile}-database",
                    },
                    {"name": "PGDATABASE", "value": "securecloud"},
                    {"name": "PGUSER", "value": "securecloud"},
                    {"name": "PGPASSWORD", "valueFrom": secret_password},
                ],
                "readinessProbe": {"httpGet": {"path": "/health", "port": "service"}, "initialDelaySeconds": 2, "periodSeconds": 3},
                "livenessProbe": {"httpGet": {"path": "/health", "port": "service"}, "initialDelaySeconds": 8, "periodSeconds": 10},
            })
            if role in {"plugin", "platform"}:  # stateless services: no database credentials
                container["env"] = [{"name": "APP_PROFILE", "value": reference_profile},
                                    {"name": "APP_STORAGE", "value": "memory"}]
            elif reference_profile in {"northstar", "bloom", "shop"}:  # shop order APIs settle through the platform zone
                container["env"].append({"name": "PLATFORM_NAMESPACE", "value": tenant_namespace(PLATFORM_TENANT_ID)})
                if reference_profile == "shop" and api_upstream:  # template shops: identity from the slug
                    container["env"].append({"name": "SHOP_ID", "value": api_upstream.removesuffix("-api")})
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

    def _ensure_namespace(
        self,
        namespace: str,
        tenant_id: str,
        *,
        purpose: str | None = None,
    ):
        labels = {
            "app.kubernetes.io/managed-by": "securecloud",
            "securecloud.io/tenant": sha256(tenant_id.encode()).hexdigest()[:16],
            "pod-security.kubernetes.io/enforce": "restricted",
            "pod-security.kubernetes.io/enforce-version": "latest",
            "pod-security.kubernetes.io/audit": "restricted",
            "pod-security.kubernetes.io/warn": "restricted",
        }
        if purpose:
            labels["securecloud.io/purpose"] = purpose
        # Template (merchant) shops only: the platform admits them by this label, and it is the only
        # label under which the backend may delete a namespace. The fixed testbed shops are admitted
        # by their purpose instead, so they can never become deletable.
        if is_shop_stack(purpose) and purpose not in LEGACY_SHOP_STACKS:
            labels["securecloud.io/kind"] = "shop"
        body = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace,
                "labels": labels,
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

    def service_request(self, tenant_id: str, service: str, port: int, path: str, *,
                        method: str = "GET", payload: dict | None = None, timeout: float = 5.0) -> tuple[int, bytes]:
        """Call a tenant service through the Kubernetes API service proxy (no port-forward).

        The request enters the cluster at the service, so the shop's own web -> API -> database
        hops are ordinary pod traffic that Cilium enforces and Hubble records.
        """
        resource = f"/api/v1/namespaces/{tenant_namespace(tenant_id)}/services/{service}:{port}/proxy/{path.lstrip('/')}"
        try:
            result = self.core.api_client.call_api(
                resource, method,
                header_params={"Content-Type": "application/json", "Accept": "application/json"},
                body=payload,
                auth_settings=["BearerToken"], _preload_content=False, _request_timeout=timeout,
            )
            # Client versions differ: some return the raw response, others (data, status, headers).
            response = result[0] if isinstance(result, tuple) else result
            return response.status, response.data
        except self.ApiException as exc:
            return exc.status or 0, (exc.body or b"") if isinstance(exc.body, bytes) else str(exc.body or "").encode()
        except Exception as exc:
            raise self._translate(exc) from exc

    # ----------------------------------------------------------------------------------- tenant views
    def _sanitize(self, obj) -> dict:
        data = self.core.api_client.sanitize_for_serialization(obj)
        (data.get("metadata") or {}).pop("managedFields", None)
        return data

    def live_policies(self, tenant_id: str) -> list[dict]:
        """The network policies actually applied in a tenant namespace, read back from the API server."""
        namespace = tenant_namespace(tenant_id)
        try:
            documents = [self._sanitize(item) for item in self.networking.list_namespaced_network_policy(namespace).items]
            try:
                cilium = self.custom.list_namespaced_custom_object("cilium.io", "v2", namespace, "ciliumnetworkpolicies")
                for item in cilium.get("items", []):
                    (item.get("metadata") or {}).pop("managedFields", None)
                    documents.append(item)
            except self.ApiException as exc:
                if exc.status not in (403, 404):
                    raise
            for item in documents:
                item.setdefault("apiVersion", "networking.k8s.io/v1")
                item.setdefault("kind", "NetworkPolicy")
            return sorted(documents, key=lambda item: (item["kind"], item["metadata"]["name"]))
        except Exception as exc:
            raise self._translate(exc) from exc

    def quota_usage(self, tenant_id: str) -> dict:
        """Used vs hard limits of the tenant's ResourceQuota (pods, CPU and memory requests/limits)."""
        try:
            quota = self.core.read_namespaced_resource_quota("securecloud-quota", tenant_namespace(tenant_id))
            hard, used = quota.status.hard or {}, quota.status.used or {}
            return {key: {"used": used.get(key, "0"), "hard": hard[key]} for key in sorted(hard)}
        except self.ApiException as exc:
            if exc.status == 404:
                return {}
            raise self._translate(exc) from exc
        except Exception as exc:
            raise self._translate(exc) from exc

    def posture(self, tenant_id: str) -> list[dict]:
        """Hardening checks for one tenant, read from the live cluster. Each check names the
        CIS Kubernetes Benchmark / NSA-CISA hardening guidance it follows. Not a full benchmark scan."""
        namespace = tenant_namespace(tenant_id)
        try:
            ns = self.core.read_namespace(namespace)
            labels = ns.metadata.labels or {}
            policies = self.networking.list_namespaced_network_policy(namespace).items
            deployments = self.apps.list_namespaced_deployment(namespace).items
            try:
                self.core.read_namespaced_resource_quota("securecloud-quota", namespace)
                quota = True
            except self.ApiException as exc:
                if exc.status != 404:
                    raise
                quota = False
        except Exception as exc:
            raise self._translate(exc) from exc
        containers, pods = [], []
        for deployment in deployments:
            spec = deployment.spec.template.spec
            pods.append((deployment.metadata.name, spec))
            for container in spec.containers:
                containers.append((deployment.metadata.name, container, spec))

        def every(predicate):
            failing = sorted({name for name, container, spec in containers if not predicate(container, spec)})
            return not failing and bool(containers), failing

        def sc(container):
            return container.security_context

        def pod_sc(spec):
            return spec.security_context

        checks = []

        def add(check_id, title, refs, passed, failing=()):
            checks.append({"id": check_id, "title": title, "refs": refs, "passed": bool(passed), "failing": list(failing)})

        add("default-deny", "Default-deny network policy", ["CIS 5.3.2", "NSA-CISA: network separation"],
            any(p.metadata.name == "default-deny" and not (p.spec.pod_selector.match_labels or p.spec.pod_selector.match_expressions) for p in policies))
        add("pod-security", "Restricted Pod Security Standard enforced", ["CIS 5.2", "NSA-CISA: pod security"],
            labels.get("pod-security.kubernetes.io/enforce") == "restricted")
        add("quota", "Resource quota on the namespace", ["NSA-CISA: resource policies"], quota)
        passed, failing = every(lambda c, spec: bool((sc(c) and sc(c).run_as_non_root) or (pod_sc(spec) and pod_sc(spec).run_as_non_root)))
        add("non-root", "Containers run as non-root", ["CIS 5.2.6", "NSA-CISA: non-root containers"], passed, failing)
        passed, failing = every(lambda c, spec: bool(sc(c) and sc(c).allow_privilege_escalation is False))
        add("no-escalation", "Privilege escalation disabled", ["CIS 5.2.5"], passed, failing)
        passed, failing = every(lambda c, spec: bool(sc(c) and sc(c).capabilities and "ALL" in (sc(c).capabilities.drop or [])))
        add("drop-caps", "All Linux capabilities dropped", ["CIS 5.2.7", "CIS 5.2.9"], passed, failing)
        passed, failing = every(lambda c, spec: bool(sc(c) and sc(c).read_only_root_filesystem))
        add("read-only-fs", "Read-only root filesystem", ["NSA-CISA: immutable filesystems"], passed, failing)
        passed, failing = every(lambda c, spec: bool(c.resources and c.resources.limits and "cpu" in c.resources.limits and "memory" in c.resources.limits))
        add("limits", "CPU and memory limits set", ["NSA-CISA: resource limits"], passed, failing)
        passed, failing = every(lambda c, spec: ":" in c.image.rsplit("/", 1)[-1] and not c.image.endswith(":latest"))
        add("pinned-images", "Images pinned to a version (no :latest)", ["NSA-CISA: image hygiene"], passed, failing)
        passed, failing = every(lambda c, spec: bool((pod_sc(spec) and pod_sc(spec).seccomp_profile and pod_sc(spec).seccomp_profile.type == "RuntimeDefault")
                                                     or (sc(c) and sc(c).seccomp_profile and sc(c).seccomp_profile.type == "RuntimeDefault")))
        add("seccomp", "Seccomp RuntimeDefault profile", ["CIS 5.7.2"], passed, failing)
        failing = sorted({name for name, spec in pods if spec.host_network or spec.host_pid or spec.host_ipc})
        add("host-namespaces", "No host network, PID or IPC", ["CIS 5.2.2", "CIS 5.2.3", "CIS 5.2.4"], not failing and bool(pods), failing)
        failing = sorted({name for name, spec in pods if spec.automount_service_account_token is not False})
        add("no-sa-token", "Service-account token not mounted", ["CIS 5.1.6"], not failing and bool(pods), failing)
        return checks

    def scale_shop(self, tenant_id: str, replicas: int) -> str:
        """Pause (0) or resume (1) a shop's workloads; "done" only once the cluster shows it.
        Labels, including any quarantine label, are never touched."""
        namespace = tenant_namespace(tenant_id)
        try:
            pending = False
            for deployment in self.apps.list_namespaced_deployment(namespace, label_selector="app.kubernetes.io/managed-by=securecloud").items:
                if (deployment.spec.replicas or 0) != replicas:
                    self.apps.patch_namespaced_deployment(deployment.metadata.name, namespace, {"spec": {"replicas": replicas}})
                    pending = True
                    continue
                current, ready = deployment.status.replicas or 0, deployment.status.ready_replicas or 0
                if (replicas == 0 and current > 0) or (replicas > 0 and ready < replicas):
                    pending = True
            return "pending" if pending else "done"
        except Exception as exc:
            raise self._translate(exc) from exc

    def delete_shop_namespace(self, tenant_id: str) -> str:
        """Delete one shop tenant's namespace. Returns "deleting" until Kubernetes confirms it is gone.

        Refuses unless the namespace really is that shop: SecureCloud-managed, kind=shop, and
        annotated with the same tenant id. Deletes with a UID precondition (never force). A cluster
        ValidatingAdmissionPolicy enforces the same managed/kind=shop rule server-side.
        """
        namespace = tenant_namespace(tenant_id)
        try:
            try:
                current = self.core.read_namespace(namespace)
            except self.ApiException as exc:
                if exc.status == 404:
                    return "deleted"
                raise
            labels = current.metadata.labels or {}
            annotations = current.metadata.annotations or {}
            if (labels.get("app.kubernetes.io/managed-by") != "securecloud" or labels.get("securecloud.io/kind") != "shop"
                    or annotations.get("securecloud.io/tenant-id") != tenant_id):
                raise InfrastructureConflict("Namespace identity does not match this shop")
            if current.metadata.deletion_timestamp is None:
                self.core.delete_namespace(namespace, body=self.client.V1DeleteOptions(
                    preconditions=self.client.V1Preconditions(uid=current.metadata.uid), propagation_policy="Foreground"))
            return "deleting"
        except InfrastructureError:
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    def set_protection(self, enabled: bool, namespaces: list[str]) -> None:
        """Apply (enabled) or remove (disabled) every SecureCloud tenant network policy."""
        try:
            for namespace in namespaces:
                if enabled:
                    self._ensure_namespace_controls(namespace)
                    continue
                for policy in self._policies(namespace):
                    try:
                        self.networking.delete_namespaced_network_policy(policy["metadata"]["name"], namespace)
                    except self.ApiException as exc:
                        if exc.status != 404:
                            raise
        except Exception as exc:
            raise self._translate(exc) from exc

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
                "podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"podSelector": {"matchLabels": {"securecloud.io/template": "web"}}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
            }),
            policy("api-to-database", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"podSelector": {"matchLabels": {"securecloud.io/template": "database"}}}], "ports": [{"protocol": "TCP", "port": 5432}]}],
            }),
            policy("database-from-api", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "database"}}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}}], "ports": [{"protocol": "TCP", "port": 5432}]}],
            }),
            policy("plugin-to-api", {
                "podSelector": {"matchLabels": {"securecloud.io/role": "plugin"}}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
            }),
            # Shop order APIs may call the platform zone; platform services accept only shop order APIs.
            policy("api-to-platform", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}, "policyTypes": ["Egress"],
                "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"securecloud.io/purpose": "platform-stack"}},
                                    "podSelector": {"matchLabels": {"securecloud.io/role": "platform"}}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
            }),
            policy("platform-from-shops", {
                "podSelector": {"matchLabels": {"securecloud.io/role": "platform"}}, "policyTypes": ["Ingress"],
                # Any shop namespace (kind=shop); the fixed testbed shops are also matched by purpose so
                # they keep access even before their namespace picks up the new label.
                "ingress": [{"from": [
                    {"namespaceSelector": {"matchLabels": {"securecloud.io/kind": "shop"}},
                     "podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}},
                    {"namespaceSelector": {"matchExpressions": [{"key": "securecloud.io/purpose", "operator": "In", "values": list(LEGACY_SHOP_STACKS)}]},
                     "podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}},
                ], "ports": [{"protocol": "TCP", "port": 8080}]}],
            }),
            policy("api-from-plugin", {
                "podSelector": {"matchLabels": {"securecloud.io/template": "api"}, "matchExpressions": [NOT_PLUGIN]}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"podSelector": {"matchLabels": {"securecloud.io/role": "plugin"}}}], "ports": [{"protocol": "TCP", "port": 8080}]}],
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
