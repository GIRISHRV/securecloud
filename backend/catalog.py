"""Server-owned catalog definitions; callers never supply images or manifests."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


TemplateId = Literal["web", "api", "database"]
StackStatus = Literal["validated", "planned"]


@dataclass(frozen=True)
class WorkloadTemplate:
    id: TemplateId
    name: str
    description: str
    cpu: float
    memory: int
    port: int


@dataclass(frozen=True)
class StackService:
    id: str
    template: TemplateId
    port: int | None
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class StackDefinition:
    id: str
    name: str
    description: str
    version: str
    status: StackStatus
    deployment_enabled: bool
    workflow: str
    services: tuple[StackService, ...]


WORKLOAD_TEMPLATES = (
    WorkloadTemplate(
        "web", "Web application",
        "A frontend service with tenant-local API access.", 0.25, 128, 80,
    ),
    WorkloadTemplate(
        "api", "API service",
        "An application service between web and database workloads.",
        0.5, 256, 8080,
    ),
    WorkloadTemplate(
        "database", "Database",
        "A tenant-local data service with no outbound application intent.",
        0.5, 512, 5432,
    ),
)


STACK_DEFINITIONS = (
    StackDefinition(
        id="retail-stack",
        name="Retail application",
        description="Functional storefront, cart, checkout, payment simulator, and supporting services.",
        version="online-boutique-v0.10.3",
        status="validated",
        deployment_enabled=False,
        workflow="Browse products, add to cart, and complete a test checkout.",
        services=(
            StackService("frontend", "web", 80, (
                "productcatalogservice", "currencyservice", "cartservice",
                "recommendationservice", "shippingservice", "checkoutservice",
                "adservice",
            )),
            StackService("adservice", "api", 9555),
            StackService("cartservice", "api", 7070, ("redis-cart",)),
            StackService("checkoutservice", "api", 5050, (
                "productcatalogservice", "shippingservice", "paymentservice",
                "emailservice", "currencyservice", "cartservice",
            )),
            StackService("currencyservice", "api", 7000),
            StackService("emailservice", "api", 5000),
            StackService("loadgenerator", "api", None, ("frontend",)),
            StackService("paymentservice", "api", 50051),
            StackService("productcatalogservice", "api", 3550),
            StackService(
                "recommendationservice", "api", 8080,
                ("productcatalogservice",),
            ),
            StackService("redis-cart", "database", 6379),
            StackService("shippingservice", "api", 50051),
        ),
    ),
    StackDefinition(
        id="facilities-vendor-stack",
        name="Facilities vendor application",
        description="Vendor portal, maintenance API, and project-owned database.",
        version="securecloud-vendor-v1",
        status="validated",
        deployment_enabled=False,
        workflow="Create and review maintenance work orders.",
        services=(
            StackService("vendor-web", "web", 80, ("vendor-api",)),
            StackService("vendor-api", "api", 8080, ("vendor-database",)),
            StackService("vendor-database", "database", 5432),
        ),
    ),
)


def catalog_response(deployable_stack_ids: frozenset[str] = frozenset()) -> dict:
    """Return a fresh JSON-safe view without deploy-time image or YAML inputs."""
    return {
        "templates": [asdict(template) for template in WORKLOAD_TEMPLATES],
        "stacks": [
            {
                "id": stack.id,
                "name": stack.name,
                "description": stack.description,
                "version": stack.version,
                "status": stack.status,
                "deployment_enabled": stack.id in deployable_stack_ids,
                "workflow": stack.workflow,
                "services": [
                    {
                        "id": service.id,
                        "template": service.template,
                        "port": service.port,
                        "dependencies": list(service.dependencies),
                    }
                    for service in stack.services
                ],
            }
            for stack in STACK_DEFINITIONS
        ],
    }


def stack_definition(stack_id: str) -> StackDefinition | None:
    return next((stack for stack in STACK_DEFINITIONS if stack.id == stack_id), None)
