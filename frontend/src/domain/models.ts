import { z } from "zod";

export const tenantIdSchema = z.string().regex(/^[a-z][a-z0-9-]{2,63}$/);
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
export const workloadSchema = z.object({
  id: text,
  tenantId: tenantIdSchema,
  templateId: templateIdSchema,
  name: z.string().regex(/^[a-z][a-z0-9-]{2,39}$/),
  status: z.enum(["running", "stopped"]),
  quarantined: z.boolean(),
  createdAt: timestamp,
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
  status: z.enum(["alert", "quarantined", "review", "restored"]),
  reason: text,
  createdAt: timestamp,
  restoredAt: timestamp.optional(),
  resetAfterEventId: text.optional(),
  evidence: z.array(trafficSchema).min(3).max(1000),
  trace: z.array(traceSchema).max(200),
});
export const stateSchema = z.object({
  version: z.literal(2),
  tenants: z.array(tenantSchema),
  demoLoaded: z.boolean(),
  workloads: z.array(workloadSchema),
  traffic: z.array(trafficSchema).max(1000),
  incidents: z.array(incidentSchema),
});

export type TenantId = z.infer<typeof tenantIdSchema>;
export type TemplateId = z.infer<typeof templateIdSchema>;
export type Tenant = z.infer<typeof tenantSchema>;
export type WorkloadTemplate = z.infer<typeof templateSchema>;
export type Workload = z.infer<typeof workloadSchema>;
export type ConnectionIntent = z.infer<typeof intentSchema>;
export type TrafficEvent = z.infer<typeof trafficSchema>;
export type TraceStep = z.infer<typeof traceSchema>;
export type Incident = z.infer<typeof incidentSchema>;
export type DemoState = z.infer<typeof stateSchema>;
export type Snapshot = { data: DemoState; storageWarning: string | null };

export interface PortalService {
  subscribe(listener: () => void): () => void;
  getSnapshot(): Snapshot;
  reset(): Promise<void>;
  loadDemo(): Promise<void>;
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
