import { z } from "zod";
import { incidentSchema, riskObservationSchema, trafficSchema } from "../domain/models";
import { orderSchema, productSchema, type Order, type Product, type RetailUser } from "../storefront/retailService";
import { ADMIN_API, IS_PROVIDER } from "../shop";

const ownerSchema = z.object({
  id: z.string(), tenant_id: z.string(), email: z.string(), display_name: z.string(),
  phone: z.string(), role: z.literal("owner"), status: z.literal("active"),
});
const sessionEnvelope = z.object({ user: ownerSchema, csrf: z.string(), session_id: z.string() });
const overviewSchema = z.object({
  orders_today: z.number().int(), revenue_today_minor: z.number().int(),
  open_orders: z.number().int(), active_customers: z.number().int(), currency: z.literal("INR"),
});
const customerSchema = z.object({
  id: z.string(), email: z.string(), display_name: z.string(), phone: z.string(), status: z.string(),
  created_at: z.number(), order_count: z.number().int(), total_spent_minor: z.number().int(), last_seen_at: z.number().nullable(),
});
const activeSessionSchema = z.object({
  id: z.string(), created_at: z.number(), expires_at: z.number(), last_seen_at: z.number(),
  client_summary: z.string(), user_id: z.string(), email: z.string(), display_name: z.string(),
  role: z.string(), active: z.boolean(),
});
const activitySchema = z.object({
  id: z.string(), occurred_at: z.number(), request_id: z.string(), tenant_id: z.string(),
  actor_id: z.string().nullable(), session_id: z.string().nullable(), source_workload: z.string(),
  destination_workload: z.string(), action: z.string(), route_template: z.string(), result: z.string(),
  protocol: z.string(), destination_port: z.number().int().nullable(),
});
const correlationSchema = z.object({
  application_event_id: z.string(), flow_event_id: z.string().nullable(),
  status: z.enum(["exact", "inconclusive", "unmatched"]), reason: z.string(),
  correlated_at: z.number(), observed_at: z.number().nullable(),
  source_workload: z.string().nullable(), source_name: z.string().nullable(),
  destination_workload: z.string().nullable(), destination_name: z.string().nullable(),
  verdict: z.string().nullable(), drop_reason: z.string().nullable(), protocol: z.string().nullable(),
  destination_port: z.number().int().nullable(),
});
const applicationEventSchema = activitySchema.extend({ correlation: correlationSchema.nullable() });
const findingSchema = z.object({
  model_version: z.string(), anomaly_score: z.number(), accumulated_risk: z.number(),
  baseline_score: z.number(), threshold: z.number(), response: z.string(),
  supporting_facts: z.record(z.string(), z.boolean()), event_ids: z.array(z.string()),
}).nullable();
const containmentSchema = z.object({
  status: z.string(), action: z.string(), error: z.string().nullable(),
}).passthrough().nullable();
const adminIncidentSchema = incidentSchema.extend({
  applicationEvents: z.array(applicationEventSchema), finding: findingSchema,
  containment: containmentSchema,
});
const securitySummarySchema = z.object({
  applicationEvents: z.array(applicationEventSchema), incidents: z.array(adminIncidentSchema),
  risk: z.array(riskObservationSchema), traffic: z.array(trafficSchema),
});
const errorSchema = z.object({ detail: z.string() });
const platformServiceSchema = z.object({
  id: z.string(), name: z.string(), tenant: z.string(), stack: z.string(), kind: z.enum(["shop", "platform", "plugin"]),
  status: z.string(), quarantined: z.boolean(), calls: z.array(z.string()),
});
export type PlatformService = z.infer<typeof platformServiceSchema>;


const labStepSchema = z.object({
  index: z.number(), label: z.string(), target: z.string(), target_id: z.string(), cross_tenant: z.boolean(),
  port: z.number(), attempts: z.number(), expect: z.enum(["allowed", "blocked"]),
  state: z.enum(["sending", "observing", "matched", "unexpected", "inconclusive"]),
  client: z.object({
    connected: z.number().optional(), failed: z.number().optional(), results: z.array(z.string()).optional(),
    checkout: z.array(z.object({ step: z.string(), status: z.number().nullable(), ms: z.number(), error: z.string().optional() })).optional(),
    order_id: z.string().nullable().optional(), complete: z.boolean().optional(),
  }).nullable(),
  verdict: z.object({
    forwarded: z.number(), dropped: z.number(), drop_reasons: z.array(z.string()), event_ids: z.array(z.string()),
    observed: z.enum(["allowed", "blocked", "not_observed"]),
  }).nullable(),
  downstream: z.array(z.object({ source: z.string(), destination: z.string(), forwarded: z.number(), dropped: z.number() })).optional(),
});
const labResultSchema = z.object({
  steps: z.number(), observed: z.number(), matched: z.number(), unexpected: z.number(), inconclusive: z.number(),
  blocked_as_expected: z.number(), expected_blocks: z.number(), order_id: z.string().nullable().optional(), order_complete: z.boolean().optional(),
}).nullable();
const labRunSummarySchema = z.object({
  id: z.string(), scenario_id: z.string(), title: z.string(), kind: z.enum(["benign", "attack", "verify"]).nullable(),
  status: z.enum(["queued", "running", "completed", "failed"]), actor: z.string(), created_at: z.number(),
  started_at: z.number().nullable(), finished_at: z.number().nullable(), error: z.string().nullable(), result: labResultSchema,
});
const labRunSchema = labRunSummarySchema.extend({
  steps: z.array(labStepSchema),
  log: z.array(z.object({ at: z.number(), kind: z.string(), text: z.string() })).default([]),
  evidence: z.object({
    source: z.object({ id: z.string(), name: z.string().nullable(), quarantined: z.boolean().nullable() }),
    risk: z.array(z.object({
      model_version: z.string(), window_start: z.number(), window_end: z.number(), destination_name: z.string(),
      anomaly_score: z.number(), accumulated_risk: z.number(), baseline_score: z.number(), threshold: z.number(),
      corroborated: z.boolean(), response: z.string(),
    })),
    incidents: z.array(z.object({ id: z.string(), status: z.string(), reason: z.string(), created_at: z.number(), restored_at: z.number().nullable() })),
  }),
});
const labScenarioSchema = z.object({
  id: z.string(), title: z.string(), kind: z.enum(["benign", "attack", "verify"]), summary: z.string(),
  what_to_watch: z.string(), tags: z.array(z.string()), source: z.string(), targets: z.array(z.string()),
});
const labStatusSchema = z.object({
  ready: z.boolean(),
  cluster: z.object({ connected: z.boolean(), version: z.string().optional(), detail: z.string().optional() }).passthrough(),
  telemetry: z.object({ enabled: z.boolean(), last_poll: z.number().nullable(), fresh: z.boolean(), accepted: z.number(), detector: z.string().nullable(), last_error: z.string().nullable() }),
  workloads: z.record(z.string(), z.object({ id: z.string(), name: z.string(), observed: z.string(), quarantined: z.boolean() }).nullable()),
  running: z.string().nullable(),
  protection: z.boolean().default(true),
  session_start: z.number().default(0),
});
export type LabStep = z.infer<typeof labStepSchema>;
export type LabRun = z.infer<typeof labRunSchema>;
export type LabRunSummary = z.infer<typeof labRunSummarySchema>;
export type LabScenario = z.infer<typeof labScenarioSchema>;
export type LabStatus = z.infer<typeof labStatusSchema>;

export type AdminOverview = z.infer<typeof overviewSchema>;
export type Customer = z.infer<typeof customerSchema>;
export type ActiveSession = z.infer<typeof activeSessionSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type SecuritySummary = z.infer<typeof securitySummarySchema>;
export type AdminIncident = z.infer<typeof adminIncidentSchema>;
export type { Order, Product, RetailUser };

export type AdminSnapshot = {
  overview: AdminOverview;
  customers: Customer[];
  sessions: ActiveSession[];
  products: Product[];
  orders: Order[];
  activity: Activity[];
  security: SecuritySummary;
  apiOnline: boolean;
};

export class AdminService {
  private csrf = "";

  private async error(response: Response, fallback: string) {
    const parsed = errorSchema.safeParse(await response.json().catch(() => null));
    return new Error(parsed.success ? parsed.data.detail : fallback);
  }

  private headers() {
    return { "Content-Type": "application/json", "X-CSRF-Token": this.csrf };
  }

  async session() {
    const response = await fetch(`${ADMIN_API}/auth/session`);
    if (response.status === 401) return null;
    if (!response.ok) throw await this.error(response, "Could not check owner session");
    const value = sessionEnvelope.safeParse(await response.json());
    if (!value.success) throw new Error("This account does not have shop-owner access");
    this.csrf = value.data.csrf;
    return value.data.user;
  }

  async login(email: string, password: string) {
    const response = await fetch(`${ADMIN_API}/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw await this.error(response, "Sign in failed");
    const raw: unknown = await response.json();
    const value = sessionEnvelope.safeParse(raw);
    if (!value.success) {
      const csrf = typeof raw === "object" && raw && "csrf" in raw ? String(raw.csrf) : "";
      await fetch(`${ADMIN_API}/auth/logout`, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf }, body: "{}" });
      throw new Error("This account does not have shop-owner access");
    }
    this.csrf = value.data.csrf;
    return value.data.user;
  }

  async logout() {
    const response = await fetch(`${ADMIN_API}/auth/logout`, { method: "POST", headers: this.headers(), body: "{}" });
    if (!response.ok) throw await this.error(response, "Sign out failed");
    this.csrf = "";
  }

  private async get<T>(path: string, schema: z.ZodType<T>) {
    const response = await fetch(path);
    if (!response.ok) throw await this.error(response, "Admin data could not be loaded");
    return schema.parse(await response.json());
  }

  async snapshot(): Promise<AdminSnapshot> {
    if (IS_PROVIDER) {  // the provider sees the security plane, never a shop's business data
      const [security, health] = await Promise.all([this.securitySummary(), fetch("/api/health").then((r) => r.ok).catch(() => false)]);
      const overview = { orders_today: 0, revenue_today_minor: 0, open_orders: 0, active_customers: 0, currency: "INR" as const };
      return { overview, customers: [], sessions: [], products: [], orders: [], activity: [], security, apiOnline: health };
    }
    const [overview, customers, sessions, products, orders, activity, security, health] = await Promise.all([
      this.get(`${ADMIN_API}/admin/overview`, overviewSchema),
      this.get(`${ADMIN_API}/admin/customers`, z.object({ items: z.array(customerSchema) })),
      this.get(`${ADMIN_API}/admin/sessions`, z.object({ items: z.array(activeSessionSchema) })),
      this.get(`${ADMIN_API}/admin/products`, z.object({ items: z.array(productSchema) })),
      this.get(`${ADMIN_API}/admin/orders`, z.object({ items: z.array(orderSchema) })),
      this.get(`${ADMIN_API}/admin/activity`, z.object({ items: z.array(activitySchema) })),
      Promise.resolve({ applicationEvents: [], incidents: [], risk: [], traffic: [] }),  // shops never see the security plane
      fetch("/api/health").then((response) => response.ok).catch(() => false),
    ]);
    return { overview, customers: customers.items, sessions: sessions.items, products: products.items, orders: orders.items, activity: activity.items, security, apiOnline: health };
  }

  async platformServices() {
    return (await this.get(`${ADMIN_API}/admin/platform/services`, z.object({ items: z.array(platformServiceSchema) }))).items;
  }

  securitySummary() {
    return this.get(`${ADMIN_API}/admin/security/summary`, securitySummarySchema);
  }

  async respondToIncident(id: string, action: "quarantine" | "review" | "restore" | "dismiss") {
    const response = await fetch(`${ADMIN_API}/admin/security/incidents/${encodeURIComponent(id)}/${action}`, {
      method: "POST", headers: this.headers(), body: "{}",
    });
    if (!response.ok) throw await this.error(response, `Could not ${action} incident`);
    return z.object({ status: z.string(), verified: z.boolean().optional() }).parse(await response.json());
  }

  async loadDemoCatalog() {
    const response = await fetch(`${ADMIN_API}/admin/demo/load`, { method: "POST", headers: this.headers(), body: "{}" });
    if (!response.ok) throw await this.error(response, "Could not load sample data");
    return z.object({ items: z.array(productSchema), sample_orders: z.number().int().default(0) }).parse(await response.json());
  }

  async updateOrderStatus(id: string, status: Order["status"]) {
    const response = await fetch(`${ADMIN_API}/admin/orders/${encodeURIComponent(id)}/status`, {
      method: "PATCH", headers: this.headers(), body: JSON.stringify({ status }),
    });
    if (!response.ok) throw await this.error(response, "Could not update order status");
    return orderSchema.parse(await response.json());
  }

  labStatus() { return this.get(`${ADMIN_API}/admin/lab/status`, labStatusSchema); }
  async labScenarios() { return (await this.get(`${ADMIN_API}/admin/lab/scenarios`, z.object({ items: z.array(labScenarioSchema) }))).items; }
  async labRuns() { return (await this.get(`${ADMIN_API}/admin/lab/runs`, z.object({ items: z.array(labRunSummarySchema) }))).items; }
  labRun(id: string) { return this.get(`${ADMIN_API}/admin/lab/runs/${encodeURIComponent(id)}`, labRunSchema); }
  async setProtection(enabled: boolean) {
    const response = await fetch(`${ADMIN_API}/admin/lab/protection`, { method: "POST", headers: this.headers(), body: JSON.stringify({ enabled }) });
    if (!response.ok) throw await this.error(response, "Could not change SecureCloud protection");
    return labStatusSchema.parse(await response.json());
  }

  async resetLab() {
    const response = await fetch(`${ADMIN_API}/admin/lab/reset`, { method: "POST", headers: this.headers(), body: "{}" });
    if (!response.ok) throw await this.error(response, "Could not reset the demo");
    return labStatusSchema.parse(await response.json());
  }

  async startLabRun(scenarioId: string) {
    const response = await fetch(`${ADMIN_API}/admin/lab/runs`, { method: "POST", headers: this.headers(), body: JSON.stringify({ scenario_id: scenarioId }) });
    if (!response.ok) throw await this.error(response, "Could not start the lab scenario");
    return labRunSchema.parse(await response.json());
  }

  async createProduct(input: Pick<Product, "sku" | "name" | "description" | "price_minor" | "stock_quantity" | "published" | "image_path">) {
    const response = await fetch(`${ADMIN_API}/admin/products`, {
      method: "POST", headers: this.headers(), body: JSON.stringify({ ...input, currency: "INR" }),
    });
    if (!response.ok) throw await this.error(response, "Could not create product");
    return productSchema.parse(await response.json());
  }

  async updateProduct(id: string, changes: Partial<Pick<Product, "stock_quantity" | "published" | "price_minor">>) {
    const response = await fetch(`${ADMIN_API}/admin/products/${encodeURIComponent(id)}`, {
      method: "PATCH", headers: this.headers(), body: JSON.stringify(changes),
    });
    if (!response.ok) throw await this.error(response, "Could not update product");
    return productSchema.parse(await response.json());
  }
}
