import { z } from "zod";
import {
  catalogSchema,
  stateSchema,
  tenantSchema,
  trafficSchema,
  type CatalogDefinition,
  type DemoState,
  type PortalService,
  type PortalSession,
  type Snapshot,
  type StackId,
  type TemplateId,
  type Tenant,
  type TenantId,
  type TrafficEvent,
  type Workload,
} from "../domain/models";

const userSchema = z.object({
  id: z.string().min(1),
  username: z.string().min(1),
  administrator: z.boolean(),
});
const sessionSchema = z.object({
  user: userSchema,
  csrf: z.string().min(16),
});
const healthSchema = z.object({
  service: z.literal("securecloud"),
  infrastructure: z
    .object({ connected: z.boolean(), provider: z.string() })
    .passthrough(),
});
const operationSchema = z
  .object({
    id: z.string().min(1),
    tenant_id: z.string().min(1),
    workload_id: z.string().min(1),
    action: z.enum(["deploy", "stop", "delete"]),
    status: z.enum([
      "queued",
      "running",
      "succeeded",
      "failed",
      "inconclusive",
    ]),
    error: z.string().nullable(),
  })
  .passthrough();
const errorSchema = z.object({ detail: z.string() });
type Operation = z.infer<typeof operationSchema>;
const stackOperationSchema = z
  .object({
    id: z.string().min(1),
    tenant_id: z.string().min(1),
    stack_deployment_id: z.string().min(1),
    action: z.literal("deploy"),
    status: z.enum([
      "queued",
      "running",
      "succeeded",
      "failed",
      "inconclusive",
    ]),
    error: z.string().nullable(),
  })
  .passthrough();
type StackOperation = z.infer<typeof stackOperationSchema>;

const emptyState = (): DemoState => ({
  version: 2,
  tenants: [],
  demoLoaded: false,
  workloads: [],
  traffic: [],
  incidents: [],
});

/** Browser client for the authenticated FastAPI management plane. */
export class ApiPortalService implements PortalService {
  readonly mode = "api" as const;
  private listeners = new Set<() => void>();
  private csrfToken = "";
  private session: PortalSession = { status: "connecting", user: null };
  private snapshot: Snapshot = { data: emptyState(), storageWarning: null };
  private catalogRequest: Promise<CatalogDefinition> | null = null;

  constructor() {
    void this.initialize();
  }

  private emit() {
    for (const listener of this.listeners) listener();
  }

  private async initialize() {
    try {
      const healthResponse = await fetch("/api/health");
      if (!healthResponse.ok) throw new Error("Management API is unavailable");
      const health = healthSchema.parse(await healthResponse.json());
      this.snapshot = {
        ...this.snapshot,
        storageWarning: health.infrastructure.connected
          ? null
          : "The management API is online, but Kubernetes is not connected.",
      };

      const response = await fetch("/api/auth/session");
      if (response.status === 401) {
        this.session = { status: "signed-out", user: null };
        this.emit();
        return;
      }
      if (!response.ok)
        throw await this.responseError(response, "Session check failed");
      this.acceptSession(sessionSchema.parse(await response.json()));
      await this.refresh();
    } catch (error) {
      this.session = { status: "signed-out", user: null };
      this.snapshot = {
        ...this.snapshot,
        storageWarning:
          error instanceof Error
            ? error.message
            : "Management API is unavailable",
      };
      this.emit();
    }
  }

  private acceptSession(value: z.infer<typeof sessionSchema>) {
    this.csrfToken = value.csrf;
    this.session = { status: "signed-in", user: value.user };
    this.emit();
  }

  private async responseError(response: Response, fallback: string) {
    const payload = errorSchema.safeParse(
      await response.json().catch(() => null),
    );
    return new Error(payload.success ? payload.data.detail : fallback);
  }

  private mutationHeaders(idempotencyKey?: string) {
    if (!this.csrfToken) throw new Error("Sign in before changing resources");
    return {
      "Content-Type": "application/json",
      "X-CSRF-Token": this.csrfToken,
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    };
  }

  private assertSignedIn() {
    if (this.session.status !== "signed-in") {
      throw new Error("Sign in to access the management API");
    }
  }

  private async refresh() {
    this.assertSignedIn();
    const response = await fetch("/api/state");
    if (!response.ok)
      throw await this.responseError(response, "Could not refresh resources");
    const data = stateSchema.parse(await response.json());
    this.snapshot = { data, storageWarning: this.snapshot.storageWarning };
    this.emit();
  }

  private async waitForOperation(operation: Operation, timeoutMs = 90_000) {
    const deadline = Date.now() + timeoutMs;
    let current = operation;
    while (current.status === "queued" || current.status === "running") {
      if (Date.now() >= deadline) {
        throw new Error(
          "The operation is still running. Refresh to check its observed state.",
        );
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      const response = await fetch(
        `/api/tenants/${encodeURIComponent(current.tenant_id)}/operations/${encodeURIComponent(current.id)}`,
      );
      if (!response.ok)
        throw await this.responseError(
          response,
          "Could not check operation status",
        );
      current = operationSchema.parse(await response.json());
    }
    await this.refresh();
    if (current.status !== "succeeded") {
      throw new Error(
        current.error ||
          (current.status === "inconclusive"
            ? "Infrastructure result is inconclusive"
            : "Infrastructure operation failed"),
      );
    }
    return current;
  }

  private async waitForStackOperation(
    operation: StackOperation,
    timeoutMs = 180_000,
  ) {
    const deadline = Date.now() + timeoutMs;
    let current = operation;
    while (current.status === "queued" || current.status === "running") {
      if (Date.now() >= deadline) {
        throw new Error(
          "The stack is still provisioning. Refresh to check its observed state.",
        );
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1_000));
      const response = await fetch(
        `/api/tenants/${encodeURIComponent(current.tenant_id)}/stack-operations/${encodeURIComponent(current.id)}`,
      );
      if (!response.ok) {
        throw await this.responseError(
          response,
          "Could not check stack operation status",
        );
      }
      current = stackOperationSchema.parse(await response.json());
    }
    await this.refresh();
    if (current.status !== "succeeded") {
      throw new Error(current.error || "Stack deployment was not verified");
    }
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = () => this.snapshot;
  getSession = () => this.session;

  async login(username: string, password: string) {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok)
      throw await this.responseError(response, "Sign in failed");
    this.acceptSession(sessionSchema.parse(await response.json()));
    await this.refresh();
  }

  async logout() {
    this.assertSignedIn();
    const response = await fetch("/api/auth/logout", {
      method: "POST",
      headers: this.mutationHeaders(),
      body: JSON.stringify({}),
    });
    if (!response.ok)
      throw await this.responseError(response, "Sign out failed");
    this.csrfToken = "";
    this.session = { status: "signed-out", user: null };
    this.snapshot = { data: emptyState(), storageWarning: null };
    this.emit();
  }

  async reset(): Promise<void> {
    throw new Error("Workspace reset is available only in browser demo mode");
  }

  async loadDemo(): Promise<void> {
    this.assertSignedIn();
    const response = await fetch("/api/demo/load", {
      method: "POST",
      headers: this.mutationHeaders(),
      body: JSON.stringify({}),
    });
    if (!response.ok)
      throw await this.responseError(response, "Could not load demo data");
    await this.refresh();
  }

  getCatalog(): Promise<CatalogDefinition> {
    this.assertSignedIn();
    if (!this.catalogRequest) {
      this.catalogRequest = fetch("/api/catalog")
        .then(async (response) => {
          if (!response.ok) {
            throw await this.responseError(response, "Could not load catalog");
          }
          return catalogSchema.parse(await response.json());
        })
        .catch((error) => {
          this.catalogRequest = null;
          throw error;
        });
    }
    return this.catalogRequest;
  }

  async deployStack(
    tenantId: TenantId,
    stackId: StackId,
    name: string,
  ): Promise<void> {
    this.assertSignedIn();
    const response = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/stacks`,
      {
        method: "POST",
        headers: this.mutationHeaders(`stack-${crypto.randomUUID()}`),
        body: JSON.stringify({ name, stack: stackId }),
      },
    );
    if (!response.ok) {
      throw await this.responseError(response, "Could not deploy stack");
    }
    await this.waitForStackOperation(
      stackOperationSchema.parse(await response.json()),
    );
  }

  async createTenant(name: string, description: string): Promise<Tenant> {
    this.assertSignedIn();
    const response = await fetch("/api/tenants", {
      method: "POST",
      headers: this.mutationHeaders(),
      body: JSON.stringify({ name, description }),
    });
    if (!response.ok)
      throw await this.responseError(response, "Could not create tenant");
    const tenant = tenantSchema.parse(await response.json());
    await this.refresh();
    return tenant;
  }

  async deploy(
    tenantId: TenantId,
    templateId: TemplateId,
    name: string,
  ): Promise<Workload> {
    this.assertSignedIn();
    const response = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/workloads`,
      {
        method: "POST",
        headers: this.mutationHeaders(`deploy-${crypto.randomUUID()}`),
        body: JSON.stringify({ name, template: templateId }),
      },
    );
    if (!response.ok)
      throw await this.responseError(response, "Could not deploy workload");
    const operation = await this.waitForOperation(
      operationSchema.parse(await response.json()),
    );
    const workload = this.snapshot.data.workloads.find(
      (candidate) => candidate.id === operation.workload_id,
    );
    if (!workload)
      throw new Error(
        "Deployment succeeded but the workload is not observable yet",
      );
    return workload;
  }

  async stop(
    tenantId: TenantId,
    id: string,
    confirmation: string,
  ): Promise<void> {
    await this.lifecycle(tenantId, id, "stop", confirmation);
  }

  async deleteWorkload(
    tenantId: TenantId,
    id: string,
    confirmation: string,
  ): Promise<void> {
    await this.lifecycle(tenantId, id, "delete", confirmation);
  }

  private async lifecycle(
    tenantId: TenantId,
    id: string,
    action: "stop" | "delete",
    confirmation: string,
  ) {
    this.assertSignedIn();
    const workload = this.snapshot.data.workloads.find(
      (candidate) => candidate.id === id && candidate.tenantId === tenantId,
    );
    if (!workload?.version)
      throw new Error("Refresh the workload before changing it");
    const response = await fetch(
      `/api/tenants/${encodeURIComponent(tenantId)}/workloads/${encodeURIComponent(id)}/${action}`,
      {
        method: "POST",
        headers: this.mutationHeaders(`${action}-${crypto.randomUUID()}`),
        body: JSON.stringify({
          confirmation,
          expected_version: workload.version,
        }),
      },
    );
    if (!response.ok)
      throw await this.responseError(response, `Could not ${action} workload`);
    await this.waitForOperation(operationSchema.parse(await response.json()));
  }

  async simulate(
    sourceId: string,
    destinationId: string,
    port: number,
  ): Promise<TrafficEvent> {
    this.assertSignedIn();
    const response = await fetch("/api/traffic/simulate", {
      method: "POST",
      headers: this.mutationHeaders(),
      body: JSON.stringify({
        source_id: sourceId,
        destination_id: destinationId,
        port,
      }),
    });
    if (!response.ok)
      throw await this.responseError(response, "Simulation failed");
    const event = trafficSchema.parse(await response.json());
    await this.refresh();
    return event;
  }

  async quarantine(incidentId: string): Promise<void> {
    await this.incidentAction(incidentId, "quarantine");
  }

  async review(incidentId: string): Promise<void> {
    await this.incidentAction(incidentId, "review");
  }

  async restore(incidentId: string): Promise<void> {
    await this.incidentAction(incidentId, "restore");
  }

  private async incidentAction(
    incidentId: string,
    action: "quarantine" | "review" | "restore",
  ) {
    this.assertSignedIn();
    const response = await fetch(
      `/api/incidents/${encodeURIComponent(incidentId)}/${action}`,
      {
        method: "POST",
        headers: this.mutationHeaders(),
        body: JSON.stringify({}),
      },
    );
    if (!response.ok)
      throw await this.responseError(response, `Could not ${action} incident`);
    await this.refresh();
  }
}
