import { z } from "zod";

export const tenantIdSchema = z
  .string()
  .refine(
    (value) =>
      /^[a-z][a-z0-9-]{2,63}$/.test(value) ||
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
        value,
      ),
    "Invalid tenant identifier",
  );
export const templateIdSchema = z.enum(["web", "api", "database"]);
const text = z.string().min(1).max(250);
const timestamp = z.number().finite().nonnegative();
export const tenantSchema = z.object({
  id: tenantIdSchema,
  name: z.string().trim().min(2).max(60),
  description: z.string().trim().max(160),
});
export const templateSchema = z.object({
  id: templateIdSchema,
  name: text,
  description: text,
  cpu: z.number().positive(),
  memory: z.number().positive(),
  port: z.number().int().positive(),
});
export const stackServiceSchema = z.object({
  id: z.string().regex(/^[a-z][a-z0-9-]{2,39}$/),
  template: templateIdSchema,
  port: z.number().int().positive().nullable(),
  dependencies: z.array(z.string().min(1)).max(20),
});
export const stackDefinitionSchema = z.object({
  id: z.enum(["retail-stack", "facilities-vendor-stack"]),
  name: text,
  description: text,
  version: z.string().min(1).max(80),
  status: z.enum(["validated", "planned"]),
  deployment_enabled: z.boolean(),
  workflow: text,
  services: z.array(stackServiceSchema).min(1).max(20),
});
export const catalogSchema = z.object({
  templates: z.array(templateSchema).length(3),
  stacks: z.array(stackDefinitionSchema).length(2),
});
export const workloadSchema = z.object({
  id: text,
  tenantId: tenantIdSchema,
  templateId: templateIdSchema,
  name: z.string().regex(/^[a-z][a-z0-9-]{2,39}$/),
  status: z.enum(["pending", "running", "stopped", "unknown"]),
  quarantined: z.boolean(),
  createdAt: timestamp,
  desired: z.enum(["running", "stopped", "deleted"]).optional(),
  version: z.number().int().positive().optional(),
  kubernetesUid: z.string().min(1).nullish(),
  kubernetesVersion: z.string().min(1).nullish(),
  previewUrl: z.string().url().nullish(),
});
export const intentSchema = z.object({
  id: text,
  tenantId: tenantIdSchema,
  source: templateIdSchema,
  destination: templateIdSchema,
  port: z.number().int().positive(),
});
export const trafficSchema = z.object({
  id: text,
  sourceId: text,
  destinationId: text,
  sourceName: text,
  destinationName: text,
  sourceTenant: tenantIdSchema,
  destinationTenant: tenantIdSchema,
  port: z.number().int().min(1).max(65535),
  at: timestamp,
  decision: z.enum(["allowed", "denied", "inconclusive"]),
  reason: z.enum([
    "approved-intent",
    "cross-tenant",
    "default-deny",
    "quarantine",
    "unavailable",
  ]),
});
export const traceSchema = z.object({
  at: timestamp,
  title: text,
  detail: z.string().min(1).max(1000),
});
export const incidentSchema = z.object({
  id: text,
  sourceId: text,
  sourceName: text,
  tenantId: tenantIdSchema,
  status: z.enum(["alert", "quarantined", "review", "restored", "closed"]),
  reason: text,
  createdAt: timestamp,
  restoredAt: timestamp.nullish(),
  resetAfterEventId: text.optional(),
  evidence: z.array(trafficSchema).min(1).max(1000),
  trace: z.array(traceSchema).max(200),
});
export const riskObservationSchema = z.object({
  modelVersion: z.string().min(1).max(80),
  windowStart: timestamp,
  windowEnd: timestamp,
  sourceId: text,
  destinationId: text,
  sourceName: text,
  destinationName: text,
  anomalyScore: z.number().min(0).max(1),
  accumulatedRisk: z.number().min(0).max(1),
  baselineScore: z.number().min(0).max(1),
  threshold: z.number().min(0).max(1),
  corroborated: z.boolean(),
  response: z.enum(["observe", "containment-recommended"]),
  tenantId: tenantIdSchema.nullable(),
});
export const securityStateSchema = z.object({
  detector: z.string().min(1).max(80),
  telemetryEnabled: z.boolean(),
  lastPoll: timestamp.nullable(),
  observations: z.array(riskObservationSchema).max(1000),
});
export const stateSchema = z.object({
  version: z.literal(2),
  tenants: z.array(tenantSchema),
  demoLoaded: z.boolean(),
  workloads: z.array(workloadSchema),
  traffic: z.array(trafficSchema).max(1000),
  incidents: z.array(incidentSchema),
  security: securityStateSchema.optional(),
});

export type TenantId = z.infer<typeof tenantIdSchema>;
export type TemplateId = z.infer<typeof templateIdSchema>;
export type Tenant = z.infer<typeof tenantSchema>;
export type WorkloadTemplate = z.infer<typeof templateSchema>;
export type StackDefinition = z.infer<typeof stackDefinitionSchema>;
export type StackId = StackDefinition["id"];
export type CatalogDefinition = z.infer<typeof catalogSchema>;
export type Workload = z.infer<typeof workloadSchema>;
export type ConnectionIntent = z.infer<typeof intentSchema>;
export type TrafficEvent = z.infer<typeof trafficSchema>;
export type TraceStep = z.infer<typeof traceSchema>;
export type Incident = z.infer<typeof incidentSchema>;
export type RiskObservation = z.infer<typeof riskObservationSchema>;
export type DemoState = z.infer<typeof stateSchema>;
export type Snapshot = { data: DemoState; storageWarning: string | null };

export type PortalMode = "demo" | "api";
export type PortalSession =
  | { status: "connecting"; user: null }
  | { status: "signed-out"; user: null }
  | {
      status: "signed-in";
      user: { id: string; username: string; administrator: boolean };
    };

export interface PortalService {
  readonly mode: PortalMode;
  subscribe(listener: () => void): () => void;
  getSnapshot(): Snapshot;
  getSession(): PortalSession;
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
  reset(): Promise<void>;
  loadDemo(): Promise<void>;
  getCatalog(): Promise<CatalogDefinition>;
  deployStack(
    tenantId: TenantId,
    stackId: StackId,
    name: string,
  ): Promise<void>;
  createTenant(name: string, description: string): Promise<Tenant>;
  deploy(
    tenantId: TenantId,
    templateId: TemplateId,
    name: string,
  ): Promise<Workload>;
  stop(tenantId: TenantId, id: string, confirmation: string): Promise<void>;
  deleteWorkload(
    tenantId: TenantId,
    id: string,
    confirmation: string,
  ): Promise<void>;
  simulate(
    sourceId: string,
    destinationId: string,
    port: number,
  ): Promise<TrafficEvent>;
  quarantine(incidentId: string): Promise<void>;
  review(incidentId: string): Promise<void>;
  restore(incidentId: string): Promise<void>;
}
