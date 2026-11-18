import type {
  ConnectionIntent,
  CatalogDefinition,
  DemoState,
  Tenant,
  TenantId,
  WorkloadTemplate,
} from "./models";

export const demoTenants: Tenant[] = [
  { id: "college", name: "College", description: "Campus services & learning" },
  {
    id: "hospital",
    name: "Hospital",
    description: "Care services & operations",
  },
];
export const templates: WorkloadTemplate[] = [
  {
    id: "web",
    name: "Web application",
    description:
      "A frontend service for your tenant. Connects to tenant-local APIs on TCP 8080.",
    cpu: 0.25,
    memory: 128,
    port: 80,
  },
  {
    id: "api",
    name: "API service",
    description:
      "An application service. Accepts tenant-local web traffic and connects to databases.",
    cpu: 0.5,
    memory: 256,
    port: 8080,
  },
  {
    id: "database",
    name: "Database",
    description:
      "A data service. Accepts tenant-local API traffic on TCP 5432; no outbound intent.",
    cpu: 0.5,
    memory: 512,
    port: 5432,
  },
];
export const catalogDefinition: CatalogDefinition = {
  templates,
  stacks: [
    {
      id: "retail-stack",
      name: "Retail application",
      description:
        "Functional storefront, cart, checkout, payment simulator, and supporting services.",
      version: "online-boutique-v0.10.3",
      status: "validated",
      deployment_enabled: false,
      workflow: "Browse products, add to cart, and complete a test checkout.",
      services: [
        {
          id: "frontend",
          template: "web",
          port: 80,
          dependencies: [
            "productcatalogservice",
            "currencyservice",
            "cartservice",
            "recommendationservice",
            "shippingservice",
            "checkoutservice",
            "adservice",
          ],
        },
        { id: "adservice", template: "api", port: 9555, dependencies: [] },
        {
          id: "cartservice",
          template: "api",
          port: 7070,
          dependencies: ["redis-cart"],
        },
        {
          id: "checkoutservice",
          template: "api",
          port: 5050,
          dependencies: [
            "productcatalogservice",
            "shippingservice",
            "paymentservice",
            "emailservice",
            "currencyservice",
            "cartservice",
          ],
        },
        {
          id: "currencyservice",
          template: "api",
          port: 7000,
          dependencies: [],
        },
        { id: "emailservice", template: "api", port: 5000, dependencies: [] },
        {
          id: "loadgenerator",
          template: "api",
          port: null,
          dependencies: ["frontend"],
        },
        {
          id: "paymentservice",
          template: "api",
          port: 50051,
          dependencies: [],
        },
        {
          id: "productcatalogservice",
          template: "api",
          port: 3550,
          dependencies: [],
        },
        {
          id: "recommendationservice",
          template: "api",
          port: 8080,
          dependencies: ["productcatalogservice"],
        },
        {
          id: "redis-cart",
          template: "database",
          port: 6379,
          dependencies: [],
        },
        {
          id: "shippingservice",
          template: "api",
          port: 50051,
          dependencies: [],
        },
      ],
    },
    {
      id: "facilities-vendor-stack",
      name: "Facilities vendor application",
      description:
        "Vendor portal, maintenance API, and project-owned database.",
      version: "securecloud-vendor-v1",
      status: "planned",
      deployment_enabled: false,
      workflow: "Create and review maintenance work orders.",
      services: [
        {
          id: "vendor-web",
          template: "web",
          port: 80,
          dependencies: ["vendor-api"],
        },
        {
          id: "vendor-api",
          template: "api",
          port: 8080,
          dependencies: ["vendor-database"],
        },
        {
          id: "vendor-database",
          template: "database",
          port: 5432,
          dependencies: [],
        },
      ],
    },
  ],
};
// The same static intent set is used before quarantine and after restore.
export const intentsForTenant = (tenantId: TenantId): ConnectionIntent[] => [
  {
    id: `${tenantId}-web-api`,
    tenantId,
    source: "web",
    destination: "api",
    port: 8080,
  },
  {
    id: `${tenantId}-api-db`,
    tenantId,
    source: "api",
    destination: "database",
    port: 5432,
  },
];
export function createEmptyWorkspace(): DemoState {
  return {
    version: 2,
    tenants: [],
    demoLoaded: false,
    workloads: [],
    traffic: [],
    incidents: [],
  };
}
export function createSeed(now = Date.now()): DemoState {
  return {
    version: 2,
    tenants: structuredClone(demoTenants),
    demoLoaded: true,
    workloads: demoTenants.flatMap((tenant) =>
      templates.map((template) => ({
        id: `${tenant.id}-${template.id}`,
        name: `${tenant.id}-${template.id}`,
        tenantId: tenant.id,
        templateId: template.id,
        status: "running" as const,
        quarantined: false,
        createdAt: now,
      })),
    ),
    traffic: [],
    incidents: [],
  };
}
