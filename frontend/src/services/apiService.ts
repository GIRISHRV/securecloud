import type {
  DemoState,
  PortalService,
  Snapshot,
  TemplateId,
  Tenant,
  TenantId,
  TrafficEvent,
  Workload,
} from "../domain/models";

/**
 * ApiPortalService connects the frontend console to the FastAPI Zero Trust Management API.
 * Demo mode is selected explicitly by PortalContext; API mode never impersonates
 * an administrator or silently presents simulated state as backend state.
 */
export class ApiPortalService implements PortalService {
  private listeners = new Set<() => void>();
  private isOnline = false;
  private initializationError = "";
  private csrfToken = "";
  private snapshot: Snapshot = {
    data: {
      version: 2,
      tenants: [],
      demoLoaded: false,
      workloads: [],
      traffic: [],
      incidents: [],
    },
    storageWarning: null,
  };

  constructor() {
    void this.initialize();
  }

  private async initialize() {
    try {
      // 1. Check API health
      const healthRes = await fetch("/api/health");
      if (!healthRes.ok) throw new Error("API offline");

      // 2. Reuse an existing authenticated session. Credential entry is deferred;
      // API mode must never ship or guess a password.
      const sessionRes = await fetch("/api/auth/session");
      if (!sessionRes.ok) throw new Error("API session required");
      const session = await sessionRes.json();
      this.csrfToken = session.csrf;

      // 3. Fetch initial live state
      await this.refresh();
      this.isOnline = true;
    } catch (error) {
      this.isOnline = false;
      this.initializationError =
        error instanceof Error ? error.message : "API unavailable";
      this.snapshot = {
        ...this.snapshot,
        storageWarning: this.initializationError,
      };
      this.emit();
    }
  }

  private assertReady() {
    if (!this.isOnline) {
      throw new Error(this.initializationError || "API is still connecting");
    }
  }

  private async refresh() {
    try {
      const res = await fetch("/api/state");
      if (res.ok) {
        const state: DemoState = await res.json();
        this.snapshot = { data: state, storageWarning: null };
        this.emit();
      }
    } catch {
      // fallback
    }
  }

  private emit() {
    for (const l of this.listeners) l();
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): Snapshot => {
    return this.snapshot;
  };

  async reset(): Promise<void> {
    this.assertReady();
    throw new Error("Reset is available only in explicit browser demo mode");
  }

  async loadDemo(): Promise<void> {
    this.assertReady();
    await fetch("/api/demo/load", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
      },
      body: JSON.stringify({}),
    });
    await this.refresh();
  }

  async createTenant(name: string, description: string): Promise<Tenant> {
    this.assertReady();
    const res = await fetch("/api/tenants", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
      },
      body: JSON.stringify({ name, description }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to create tenant" }));
      throw new Error(err.detail || "Failed to create tenant");
    }
    const tenant: Tenant = await res.json();
    await this.refresh();
    return tenant;
  }

  async deploy(
    tenantId: TenantId,
    templateId: TemplateId,
    name: string,
  ): Promise<Workload> {
    this.assertReady();
    const res = await fetch(`/api/tenants/${tenantId}/workloads`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
        "Idempotency-Key": `dep-${Date.now()}-${name}`,
      },
      body: JSON.stringify({ name, template: templateId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to deploy workload" }));
      throw new Error(err.detail || "Failed to deploy workload");
    }
    await this.refresh();
    const created = this.snapshot.data.workloads.find((w) => w.name === name);
    return created!;
  }

  async stop(
    tenantId: TenantId,
    id: string,
    confirmation: string,
  ): Promise<void> {
    this.assertReady();
    const res = await fetch(`/api/tenants/${tenantId}/workloads/${id}/stop`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
        "Idempotency-Key": `stop-${Date.now()}-${id}`,
      },
      body: JSON.stringify({ confirmation, expected_version: 1 }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to stop workload" }));
      throw new Error(err.detail || "Failed to stop workload");
    }
    await this.refresh();
  }

  async deleteWorkload(
    tenantId: TenantId,
    id: string,
    confirmation: string,
  ): Promise<void> {
    this.assertReady();
    const res = await fetch(`/api/tenants/${tenantId}/workloads/${id}/delete`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
        "Idempotency-Key": `del-${Date.now()}-${id}`,
      },
      body: JSON.stringify({ confirmation, expected_version: 1 }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Failed to delete workload" }));
      throw new Error(err.detail || "Failed to delete workload");
    }
    await this.refresh();
  }

  async simulate(
    sourceId: string,
    destinationId: string,
    port: number,
  ): Promise<TrafficEvent> {
    this.assertReady();
    const res = await fetch("/api/traffic/simulate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
      },
      body: JSON.stringify({
        source_id: sourceId,
        destination_id: destinationId,
        port,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Simulation failed" }));
      throw new Error(err.detail || "Simulation failed");
    }
    const event: TrafficEvent = await res.json();
    await this.refresh();
    return event;
  }

  async quarantine(incidentId: string): Promise<void> {
    this.assertReady();
    const res = await fetch(`/api/incidents/${incidentId}/quarantine`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
      },
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error("Failed to quarantine incident");
    await this.refresh();
  }

  async review(incidentId: string): Promise<void> {
    this.assertReady();
    const res = await fetch(`/api/incidents/${incidentId}/review`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
      },
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error("Failed to start review");
    await this.refresh();
  }

  async restore(incidentId: string): Promise<void> {
    this.assertReady();
    const res = await fetch(`/api/incidents/${incidentId}/restore`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.csrfToken,
      },
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error("Failed to restore incident");
    await this.refresh();
  }
}
