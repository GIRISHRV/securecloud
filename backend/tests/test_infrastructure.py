import time
from pathlib import Path
from types import SimpleNamespace

from backend.infrastructure.base import StackRequest, WorkloadObservation, WorkloadRequest
from backend.infrastructure.kubernetes import KubernetesInfrastructure, TEMPLATES, tenant_namespace, workload_label
from backend.infrastructure.memory import MemoryInfrastructure
from backend.catalog import stack_definition
from backend.store import Store


def create_operation(store: Store, operation_id: str = "operation-1"):
    user_id = store.create_user("operator", "a-secure-test-password", administrator=True)
    with store.connect() as db:
        db.execute(
            "INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
            ("tenant-1", "Tenant 1", "", time.time()),
        )
        db.execute(
            "INSERT INTO workloads(id,tenant_id,name,template,desired,created) VALUES(?,?,?,?,?,?)",
            ("workload-1", "tenant-1", "tenant-web", "web", "running", time.time()),
        )
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (operation_id, user_id, "tenant-1", "workload-1", "deploy", "queued", "operation-key", "fingerprint", time.time(), None),
        )


def test_memory_adapter_reconciles_persisted_operation(tmp_path):
    store = Store(tmp_path / "state.sqlite", infrastructure=MemoryInfrastructure())
    create_operation(store)

    store.reconcile_operations()

    with store.connect() as db:
        operation = db.execute("SELECT * FROM operations").fetchone()
        workload = db.execute("SELECT * FROM workloads").fetchone()
        assert operation["status"] == "succeeded"
        assert workload["observed"] == "running"
        assert workload["kubernetes_uid"] == "test-workload-1"
        assert workload["kubernetes_version"] == "1"


def test_disabled_infrastructure_is_inconclusive_not_simulated(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    create_operation(store)

    store.reconcile_operations()

    with store.connect() as db:
        operation = db.execute("SELECT * FROM operations").fetchone()
        workload = db.execute("SELECT * FROM workloads").fetchone()
        assert operation["status"] == "inconclusive"
        assert workload["observed"] == "unknown"
        assert workload["kubernetes_uid"] is None
        assert "not configured" in operation["error"]


def test_memory_adapter_reconciles_persisted_retail_stack(tmp_path):
    infrastructure = MemoryInfrastructure()
    store = Store(tmp_path / "stack.sqlite", infrastructure=infrastructure)
    user_id = store.create_user(
        "stack-operator", "a-secure-test-password", administrator=True
    )
    definition = stack_definition("retail-stack")
    assert definition is not None
    with store.connect() as db:
        db.execute(
            "INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
            ("retail", "Retail", "", time.time()),
        )
        db.execute(
            """INSERT INTO stack_deployments
               (id,tenant_id,name,stack_id,desired,created)
               VALUES('stack-1','retail','retail-app','retail-stack','running',?)""",
            (time.time(),),
        )
        for service in definition.services:
            db.execute(
                """INSERT INTO workloads
                   (id,tenant_id,name,template,desired,created,stack_deployment_id)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    f"component-{service.id}",
                    "retail",
                    service.id,
                    service.template,
                    "running",
                    time.time(),
                    "stack-1",
                ),
            )
        db.execute(
            """INSERT INTO stack_operations
               VALUES('stack-op-1',?,'retail','stack-1','deploy','queued',
                      'stack-key','stack-fingerprint',?,NULL)""",
            (user_id, time.time()),
        )

    store.reconcile_stack_operations()

    with store.connect() as db:
        operation = db.execute("SELECT * FROM stack_operations").fetchone()
        stack = db.execute("SELECT * FROM stack_deployments").fetchone()
        workloads = db.execute(
            "SELECT * FROM workloads ORDER BY name"
        ).fetchall()
    assert operation["status"] == "succeeded"
    assert stack["observed"] == "running"
    assert len(workloads) == 12
    assert all(row["observed"] == "running" for row in workloads)
    assert all(row["kubernetes_uid"].startswith("test-") for row in workloads)


def test_bounded_templates_and_policy_graph():
    assert set(TEMPLATES) == {"web", "api", "database"}
    assert len(tenant_namespace("tenant-1")) <= 63

    policies = {item["metadata"]["name"]: item for item in KubernetesInfrastructure._policies("sc-test")}
    assert policies["default-deny"]["spec"] == {
        "podSelector": {},
        "policyTypes": ["Ingress", "Egress"],
    }
    assert policies["web-to-api"]["spec"]["egress"][0]["ports"][0]["port"] == 8080
    assert policies["api-to-database"]["spec"]["egress"][0]["ports"][0]["port"] == 5432
    assert "database-from-api" in policies


def test_quarantine_policy_is_workload_scoped_and_denies_both_directions():
    request = WorkloadRequest("workload-1", "tenant-1", "tenant-web", "web")
    policy = KubernetesInfrastructure._quarantine_policy(
        request, "sc-test", "quarantine-test"
    )

    assert policy["kind"] == "CiliumNetworkPolicy"
    assert policy["spec"]["endpointSelector"]["matchLabels"] == {
        "securecloud.io/workload": workload_label(request.id)
    }
    ingress_deny = policy["spec"]["ingressDeny"]
    assert {"key": "k8s:io.kubernetes.pod.namespace", "operator": "Exists"} in ingress_deny[0]["fromEndpoints"][0]["matchExpressions"]
    assert {"world", "remote-node"} <= set(ingress_deny[1]["fromEntities"])
    # Only kubelet probes from the local node remain, so quarantine does not crash-loop the pod.
    assert policy["spec"]["ingress"] == [{"fromEntities": ["host"]}]
    assert policy["spec"]["egressDeny"] == [{"toEntities": ["all"]}]


def test_restore_restarts_the_same_observed_deployment():
    infrastructure = object.__new__(KubernetesInfrastructure)
    deployment = SimpleNamespace(
        metadata=SimpleNamespace(uid="deployment-uid", resource_version="27")
    )
    patches = []
    infrastructure.apps = SimpleNamespace(
        read_namespaced_deployment=lambda name, namespace: deployment,
        patch_namespaced_deployment=lambda name, namespace, body: patches.append(
            (name, namespace, body)
        ),
    )
    request = WorkloadRequest(
        "workload-1",
        "tenant-1",
        "tenant-web",
        "web",
        "deployment-uid",
        "20",
    )

    infrastructure._restart_deployment_after_restore(
        request, "sc-test", "quarantine-policy-uid"
    )

    assert patches == [
        (
            "tenant-web",
            "sc-test",
            {
                "metadata": {"resourceVersion": "27"},
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "securecloud.io/restored-from-policy": "quarantine-policy-uid"
                            }
                        }
                    }
                },
            },
        )
    ]


def test_containment_request_is_persisted_and_reconciled(tmp_path):
    infrastructure = MemoryInfrastructure()
    store = Store(tmp_path / "containment.sqlite", infrastructure=infrastructure)
    administrator = store.create_user("lab-admin", "a-secure-test-password", administrator=True)
    store.seed_demo_data(administrator)
    store.create_incident({
        "id": "incident-1", "sourceId": "college-web", "sourceName": "college-web",
        "tenantId": "college", "status": "alert", "reason": "test",
        "createdAt": time.time(), "evidence": [], "trace": [],
    })

    store.request_containment("incident-1", "quarantine", administrator)
    store.reconcile_containment_requests()
    with store.connect() as db:
        incident = db.execute("SELECT status FROM incidents WHERE id='incident-1'").fetchone()
        workload = db.execute("SELECT quarantined FROM workloads WHERE id='college-web'").fetchone()
        request = db.execute("SELECT status,policy_uid FROM containment_requests").fetchone()
    assert incident["status"] == "quarantined"
    assert workload["quarantined"] == 1
    assert request["status"] == "succeeded"
    assert request["policy_uid"] == "test-policy-college-web"

    store.update_incident_status(
        "incident-1",
        "review",
        {"at": time.time(), "title": "Review started", "detail": "test"},
        actor=administrator,
    )
    store.request_containment("incident-1", "restore", administrator)
    store.reconcile_containment_requests()
    with store.connect() as db:
        incident = db.execute("SELECT status FROM incidents WHERE id='incident-1'").fetchone()
        workload = db.execute("SELECT quarantined FROM workloads WHERE id='college-web'").fetchone()
    assert incident["status"] == "restored"
    assert workload["quarantined"] == 0
    assert "college-web" not in infrastructure.quarantined


def test_unverified_containment_does_not_claim_workload_is_quarantined(tmp_path):
    store = Store(tmp_path / "unverified.sqlite")
    administrator = store.create_user("lab-admin", "a-secure-test-password", administrator=True)
    store.seed_demo_data(administrator)
    store.create_incident({
        "id": "incident-1", "sourceId": "college-web", "sourceName": "college-web",
        "tenantId": "college", "status": "alert", "reason": "test",
        "createdAt": time.time(), "evidence": [], "trace": [],
    })

    store.request_containment("incident-1", "quarantine", administrator)
    store.reconcile_containment_requests()

    with store.connect() as db:
        incident = db.execute("SELECT status FROM incidents WHERE id='incident-1'").fetchone()
        workload = db.execute("SELECT quarantined FROM workloads WHERE id='college-web'").fetchone()
        request = db.execute("SELECT status FROM containment_requests").fetchone()
    assert request["status"] == "inconclusive"
    assert incident["status"] == "alert"
    assert workload["quarantined"] == 0


def test_memory_adapter_enforces_observed_identity():
    infrastructure = MemoryInfrastructure()
    request = WorkloadRequest("workload-1", "tenant-1", "tenant-web", "web")
    observed = infrastructure.reconcile("deploy", request)
    stale = WorkloadRequest(
        request.id,
        request.tenant_id,
        request.name,
        request.template,
        observed.uid,
        "stale-version",
    )

    try:
        infrastructure.reconcile("stop", stale)
    except Exception as exc:
        assert "version changed" in str(exc).lower()
    else:
        raise AssertionError("Stale resource version was accepted")


def test_reference_tenants_use_profile_images_and_secret_references():
    infrastructure = object.__new__(KubernetesInfrastructure)
    template = TEMPLATES["api"]
    request = WorkloadRequest("hospital-api", "hospital", "hospital-api", "api")

    container, security_context, volumes = infrastructure._container_spec(
        request, template, "hospital"
    )

    assert container["image"] == "docker.io/securecloud/reference-api:0.2.0"
    assert {item["name"]: item.get("value") for item in container["env"]}["PGHOST"] == "hospital-database"
    password = next(item for item in container["env"] if item["name"] == "PGPASSWORD")
    assert password["valueFrom"]["secretKeyRef"]["name"] == "securecloud-reference-db"
    assert security_context["runAsUser"] == 10001
    assert volumes == []


def test_reference_database_is_non_root_read_only_and_persistent():
    infrastructure = object.__new__(KubernetesInfrastructure)
    request = WorkloadRequest("college-database", "college", "college-database", "database")

    container, security_context, volumes = infrastructure._container_spec(
        request, TEMPLATES["database"], "college"
    )

    assert container["image"] == "docker.io/library/postgres:17.7-alpine3.23"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert security_context["runAsNonRoot"] is True
    assert security_context["runAsUser"] == 70
    assert volumes[0]["persistentVolumeClaim"]["claimName"] == "college-database-data"
    assert container["startupProbe"]["exec"]["command"][0] == "pg_isready"


def test_facilities_vendor_components_use_the_vendor_profile_and_service_names():
    infrastructure = object.__new__(KubernetesInfrastructure)
    api = WorkloadRequest("vendor-api-id", "vendor-tenant", "vendor-api", "api")
    container, _, _ = infrastructure._container_spec(
        api,
        TEMPLATES["api"],
        "facilities-vendor",
        database_upstream="vendor-database",
    )
    environment = {item["name"]: item.get("value") for item in container["env"]}
    assert container["image"] == "docker.io/securecloud/reference-api:0.3.0"
    assert environment["APP_PROFILE"] == "facilities-vendor"
    assert environment["PGHOST"] == "vendor-database"

    web = WorkloadRequest("vendor-web-id", "vendor-tenant", "vendor-web", "web")
    container, _, _ = infrastructure._container_spec(
        web,
        TEMPLATES["web"],
        "facilities-vendor",
        api_upstream="vendor-api",
    )
    assert container["env"] == [{"name": "API_UPSTREAM", "value": "vendor-api"}]


def test_facilities_vendor_stack_reconciles_all_three_bounded_components():
    definition = stack_definition("facilities-vendor-stack")
    assert definition is not None
    infrastructure = object.__new__(KubernetesInfrastructure)
    calls = []

    def apply_profile(workload, **options):
        calls.append((workload, options))
        return WorkloadObservation("running", f"uid-{workload.name}", "1")

    infrastructure._apply_profile_workload = apply_profile
    components = {
        service.id: WorkloadRequest(
            f"workload-{service.id}",
            "vendor-tenant",
            service.id,
            service.template,
        )
        for service in definition.services
    }
    result = infrastructure._deploy_facilities_vendor_stack(
        StackRequest(
            "vendor-stack-id",
            "vendor-tenant",
            "facilities-app",
            "facilities-vendor-stack",
        ),
        components,
    )

    assert result.state == "running"
    assert set(result.components) == {"vendor-web", "vendor-api", "vendor-database"}
    assert all(options["reference_profile"] == "facilities-vendor" for _, options in calls)
    assert all(options["namespace_purpose"] == "facilities-vendor-stack" for _, options in calls)


def test_reference_lab_queues_six_real_reconciliation_operations(tmp_path):
    store = Store(tmp_path / "reference-lab.sqlite", infrastructure=MemoryInfrastructure())
    administrator = store.create_user("lab-admin", "a-secure-test-password", administrator=True)

    store.provision_reference_lab(administrator)

    with store.connect() as db:
        tenants = db.execute("SELECT id FROM tenants ORDER BY id").fetchall()
        workloads = db.execute("SELECT tenant_id,name,template,observed FROM workloads ORDER BY name").fetchall()
        operations = db.execute("SELECT action,status FROM operations").fetchall()
    assert [row["id"] for row in tenants] == ["college", "hospital"]
    assert len(workloads) == 6
    assert {row["template"] for row in workloads} == {"web", "api", "database"}
    assert all(row["observed"] == "pending" for row in workloads)
    assert len(operations) == 6
    assert all(row["action"] == "deploy" and row["status"] == "queued" for row in operations)


def test_rollout_is_not_ready_while_old_replicaset_is_available():
    deployment = SimpleNamespace(
        spec=SimpleNamespace(replicas=1),
        metadata=SimpleNamespace(generation=2),
        status=SimpleNamespace(
            observed_generation=2,
            updated_replicas=1,
            available_replicas=1,
            replicas=2,
            unavailable_replicas=1,
        ),
    )
    assert KubernetesInfrastructure._deployment_ready(deployment) is False

    deployment.status.replicas = 1
    deployment.status.unavailable_replicas = 0
    assert KubernetesInfrastructure._deployment_ready(deployment) is True


def test_retail_stack_reconciler_applies_only_verified_bounded_resources():
    source = Path(
        "runtime/vendor-spikes/online-boutique/release/kubernetes-manifests.yaml"
    )
    if not source.exists():
        return
    definition = stack_definition("retail-stack")
    assert definition is not None
    infrastructure = object.__new__(KubernetesInfrastructure)
    infrastructure.retail_manifest = source
    applied = []
    infrastructure._ensure_namespace = lambda namespace, tenant: applied.append(
        ("Namespace", namespace, tenant)
    )
    infrastructure._apply_namespace = lambda name, body: applied.append(
        ("NamespaceApply", name, body)
    )

    def apply(method, name, namespace, body):
        applied.append((body["kind"], name, namespace, body))
        if body["kind"] != "Deployment":
            return SimpleNamespace()
        return SimpleNamespace(
            spec=SimpleNamespace(replicas=1),
            metadata=SimpleNamespace(
                uid=f"uid-{name}", resource_version="1", generation=1
            ),
            status=SimpleNamespace(
                observed_generation=1,
                updated_replicas=1,
                available_replicas=1,
                replicas=1,
                unavailable_replicas=0,
            ),
        )

    infrastructure._apply = apply
    infrastructure.core = SimpleNamespace(
        patch_namespaced_resource_quota=object(),
        patch_namespaced_service=object(),
    )
    infrastructure.networking = SimpleNamespace(
        patch_namespaced_network_policy=object()
    )
    infrastructure.apps = SimpleNamespace(patch_namespaced_deployment=object())
    components = {
        service.id: WorkloadRequest(
            f"workload-{service.id}",
            "retail-tenant",
            service.id,
            service.template,
        )
        for service in definition.services
    }

    observation = infrastructure._deploy_retail_stack(
        StackRequest(
            "stack-1", "retail-tenant", "retail-app", "retail-stack"
        ),
        components,
    )

    assert observation.state == "running"
    assert len(observation.components) == 12
    assert sum(item[0] == "Deployment" for item in applied) == 12
    assert sum(item[0] == "Service" for item in applied) == 11
    assert sum(item[0] == "NamespaceApply" for item in applied) == 1
    assert not any(item[0] == "ServiceAccount" for item in applied)
    frontend = next(
        item[3]
        for item in applied
        if item[0] == "Deployment" and item[1] == "frontend"
    )
    labels = frontend["spec"]["template"]["metadata"]["labels"]
    assert labels["securecloud.io/template"] == "web"
