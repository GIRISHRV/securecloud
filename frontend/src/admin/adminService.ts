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
const providerShopSchema = z.object({
  slug: z.string(), name: z.string(), tagline: z.string(), theme: z.string(), fixed: z.boolean(),
  state: z.string(), status: z.string(),
  owner: z.object({ email: z.string(), display_name: z.string() }).nullable(),
  tenant_id: z.string().nullable(), created_at: z.number(),
  mode: z.enum(["learn", "monitor", "protect"]).optional(), mode_auto: z.boolean().optional(), staff: z.number().optional(),
}).passthrough();
export type ProviderShop = z.infer<typeof providerShopSchema>;
const usageSchema = z.record(z.string(), z.object({ used: z.string(), hard: z.string() }));
const postureSchema = z.object({ score: z.number().nullable(), passed: z.number(), total: z.number(),
  checks: z.array(z.object({ id: z.string(), title: z.string(), refs: z.array(z.string()), passed: z.boolean(), failing: z.array(z.string()) })) });
const adviceSchema = z.object({ window_seconds: z.number(),
  unused_permissions: z.array(z.object({ source: z.string(), destination: z.string(), recommendation: z.string() })),
  blocked_paths: z.array(z.object({ source: z.string(), destination: z.string(), port: z.number().nullable(), attempts: z.number(), last_seen: z.number(),
    cross_tenant: z.boolean(), suspicious_source: z.boolean(), recommendation: z.string(), draft: z.string().optional() })) });
const scorecardSchema = z.object({ runs: z.number(), prevention_rate: z.number().nullable(), prevention: z.object({ blocked: z.number(), expected: z.number(), unverified: z.number().default(0) }),
  baseline_prevention_rate: z.number().nullable().default(null),
  detection_rate: z.number().nullable(), detection: z.object({ detected: z.number(), attack_runs: z.number() }),
  false_positive_rate: z.number().nullable(), false_positives: z.object({ flagged: z.number(), benign_runs: z.number() }),
  time_to_detect_s: z.number().nullable(), containment_time_s: z.number().nullable(), containments: z.number(),
  overhead: z.object({ order_ms_on: z.number().nullable(), order_ms_off: z.number().nullable(), delta_ms: z.number().nullable(), runs_on: z.number(), runs_off: z.number() }),
  recent: z.array(z.object({ run: z.string(), title: z.string(), kind: z.string(), mitre: z.array(z.string()), at: z.number(),
    blocked: z.number().nullable().optional(), expected_blocks: z.number().nullable().optional(), detected: z.boolean(), false_positive: z.boolean().optional() })) });
const teamSchema = z.object({ owner_is_you: z.boolean(), members: z.array(z.object({ user_id: z.string(), email: z.string(), display_name: z.string(), added_at: z.number() })) });
export type Posture = z.infer<typeof postureSchema>;
export type Advice = z.infer<typeof adviceSchema>;
export type Scorecard = z.infer<typeof scorecardSchema>;
export type Usage = z.infer<typeof usageSchema>;
export type Team = z.infer<typeof teamSchema>;


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
  mitre: z.array(z.object({ id: z.string(), name: z.string() })).default([]),
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

  async uploadImage(file: File) {
    if (file.size > 3 * 1024 * 1024) throw new Error("Images must be 3 MB or smaller");
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("Could not read the file"));
      reader.readAsDataURL(file);
    });
    const response = await fetch(`${ADMIN_API}/admin/media`, { method: "POST", headers: this.headers(), body: JSON.stringify({ data }) });
    if (!response.ok) throw await this.error(response, "Could not upload the image");
    return z.object({ path: z.string() }).parse(await response.json()).path;
  }

  private async send<T>(path: string, method: string, body: unknown, schema: z.ZodType<T>, fallback: string) {
    const response = await fetch(path, { method, headers: this.headers(), body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) throw await this.error(response, fallback);
    return response.status === 204 ? (undefined as T) : schema.parse(await response.json());
  }

  setShopMode(slug: string, mode: "learn" | "monitor" | "protect") {
    return this.send(`${ADMIN_API}/admin/shops/${encodeURIComponent(slug)}/mode`, "POST", { mode }, providerShopSchema, "Could not change the mode");
  }
  shopLifecycle(slug: string, action: "pause" | "resume", confirm: string) {
    return this.send(`${ADMIN_API}/admin/shops/${encodeURIComponent(slug)}/${action}`, "POST", { confirm }, providerShopSchema, `Could not ${action} the shop`);
  }
  shopPolicies(slug: string) { return this.get(`${ADMIN_API}/admin/shops/${encodeURIComponent(slug)}/policies`, z.object({ documents: z.number(), yaml: z.string() })); }
  shopPosture(slug: string) { return this.get(`${ADMIN_API}/admin/shops/${encodeURIComponent(slug)}/posture`, postureSchema); }
  shopUsage(slug: string) { return this.get(`${ADMIN_API}/admin/shops/${encodeURIComponent(slug)}/usage`, usageSchema); }
  policyAdvice() { return this.get(`${ADMIN_API}/admin/policy/advice`, adviceSchema); }
  labScorecard() { return this.get(`${ADMIN_API}/admin/lab/scorecard`, scorecardSchema); }
  async evidence(incidentId: string) {
    const response = await fetch(`${ADMIN_API}/admin/security/incidents/${encodeURIComponent(incidentId)}/evidence`);
    if (!response.ok) throw await this.error(response, "Could not build the evidence pack");
    return response.blob();
  }
  // Shop owner (mall) endpoints: same shared session, so the same CSRF token works.
  ownerUsage(slug: string) { return this.get(`/api/mall/shops/${encodeURIComponent(slug)}/usage`, usageSchema); }
  ownerLifecycle(slug: string, action: "pause" | "resume", confirm: string) {
    return this.send(`/api/mall/shops/${encodeURIComponent(slug)}/${action}`, "POST", { confirm }, z.object({ state: z.string() }).passthrough(), `Could not ${action} the shop`);
  }
  team(slug: string) { return this.get(`/api/mall/shops/${encodeURIComponent(slug)}/team`, teamSchema); }
  addMember(slug: string, email: string) { return this.send(`/api/mall/shops/${encodeURIComponent(slug)}/team`, "POST", { email }, z.object({ id: z.string() }).passthrough(), "Could not add that person"); }
  removeMember(slug: string, userId: string) { return this.send(`/api/mall/shops/${encodeURIComponent(slug)}/team/${encodeURIComponent(userId)}`, "DELETE", undefined, z.undefined(), "Could not remove that person"); }

  async providerShops() {
    return this.get(`${ADMIN_API}/admin/shops`, z.object({ items: z.array(providerShopSchema), quota: z.object({ used: z.number(), limit: z.number() }) }));
  }

  async removeShop(slug: string, confirm: string) {
    const response = await fetch(`${ADMIN_API}/admin/shops/${encodeURIComponent(slug)}/remove`, {
      method: "POST", headers: this.headers(), body: JSON.stringify({ confirm }),
    });
    if (!response.ok) throw await this.error(response, "Could not remove the shop");
    return providerShopSchema.parse(await response.json());
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
