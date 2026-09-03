import type {
  ConnectionIntent,
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
