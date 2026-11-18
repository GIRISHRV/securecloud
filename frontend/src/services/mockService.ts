import {
  stateSchema,
  tenantIdSchema,
  tenantSchema,
  templateIdSchema,
  workloadSchema,
} from "../domain/models";
import type {
  CatalogDefinition,
  DemoState,
  Incident,
  PortalService,
  PortalSession,
  Snapshot,
  StackId,
  TenantId,
  TemplateId,
  Workload,
} from "../domain/models";
import {
  catalogDefinition,
  createEmptyWorkspace,
  createSeed,
} from "../domain/seed";
import {
  decide,
  DENIAL_THRESHOLD,
  reasonLabels,
  WINDOW_MS,
} from "../domain/policy";

export const STORAGE_KEY = "securecloud:workspace:v2";
type StorageAdapter = Pick<Storage, "getItem" | "setItem">;

function validRelations(data: DemoState) {
  const tenantIds = new Set(data.tenants.map((t) => t.id));
  if (
    tenantIds.size !== data.tenants.length ||
    new Set(data.tenants.map((t) => t.name.toLowerCase())).size !==
      data.tenants.length
  )
    return false;
  if (
    data.workloads.some((w) => !tenantIds.has(w.tenantId)) ||
    data.incidents.some((i) => !tenantIds.has(i.tenantId))
  )
    return false;
  if (
    data.traffic.some(
      (e) =>
        !tenantIds.has(e.sourceTenant) || !tenantIds.has(e.destinationTenant),
    )
  )
    return false;
  if (
    data.tenants.some(
      (t) => data.workloads.filter((w) => w.tenantId === t.id).length > 12,
    )
  )
    return false;
  const ids = new Set(data.workloads.map((w) => w.id));
  if (ids.size !== data.workloads.length) return false;
  if (
    new Set(data.workloads.map((w) => `${w.tenantId}:${w.name}`)).size !==
    data.workloads.length
  )
    return false;
  if (new Set(data.incidents.map((i) => i.id)).size !== data.incidents.length)
    return false;
  return (
    data.incidents.every(
      (i) =>
        i.status === "restored" ||
        data.workloads.some(
          (w) =>
            w.id === i.sourceId &&
            w.tenantId === i.tenantId &&
            w.quarantined === (i.status !== "alert"),
        ),
    ) &&
    data.workloads.every(
      (w) =>
        !w.quarantined ||
        data.incidents.some(
          (i) =>
            i.sourceId === w.id && ["quarantined", "review"].includes(i.status),
        ),
    ) &&
    data.workloads.every(
      (w) =>
        data.incidents.filter(
          (i) => i.sourceId === w.id && i.status !== "restored",
        ).length <= 1,
    )
  );
}

export class MockPortalService implements PortalService {
  readonly mode = "demo" as const;
  private snapshot: Snapshot;
  private listeners = new Set<() => void>();
  private storage?: StorageAdapter;
  private clock: () => number;
  private readonly localSession: PortalSession = {
    status: "signed-in",
    user: {
      id: "local-operator",
      username: "Local operator",
      administrator: true,
    },
  };

  constructor(storage?: StorageAdapter, clock = Date.now) {
    this.storage = storage;
    this.clock = clock;
    this.snapshot = {
      data: createEmptyWorkspace(),
      storageWarning: storage
        ? null
        : "Browser storage is unavailable. Changes last only for this session.",
    };
    if (storage) {
      try {
        const raw = storage.getItem(STORAGE_KEY);
        if (raw) {
          const result = stateSchema.safeParse(JSON.parse(raw));
          if (!result.success || !validRelations(result.data))
            throw new Error("Invalid demo state");
          this.snapshot.data = result.data;
        }
      } catch {
        this.snapshot.storageWarning =
          "Saved workspace could not be loaded. An empty workspace is shown. Clear the workspace to replace the saved data.";
      }
    }
  }

  getSnapshot = () => this.snapshot;
  getSession = () => this.localSession;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  async login(): Promise<void> {}

  async getCatalog(): Promise<CatalogDefinition> {
    return structuredClone(catalogDefinition);
  }

  async deployStack(
    _tenantId: TenantId,
    _stackId: StackId,
    _name: string,
  ): Promise<void> {
    throw new Error("Composite deployment is available only in API mode");
  }

  async logout(): Promise<void> {}

  private commit(data: DemoState) {
    let warning: string | null = null;
    try {
      if (!this.storage) throw new Error("Unavailable");
      this.storage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch {
      warning =
        "Changes are in memory only. Browser storage is unavailable or full; refreshing may lose changes.";
    }
    this.snapshot = { data, storageWarning: warning };
    this.listeners.forEach((listener) => listener());
  }

  private workload(data: DemoState, id: string, tenantId?: TenantId) {
    const workload = data.workloads.find((w) => w.id === id);
    if (!workload || (tenantId && workload.tenantId !== tenantId))
      throw new Error("Workload not found in the selected tenant.");
    return workload;
  }

  async reset() {
    this.commit(createEmptyWorkspace());
  }

  async createTenant(name: string, description: string) {
    const parsed = tenantSchema.safeParse({
      id: `tenant-${crypto.randomUUID()}`,
      name,
      description,
    });
    if (!parsed.success)
      throw new Error(
        "Enter a tenant name of 2–60 characters and a description of up to 160 characters.",
      );
    const data = structuredClone(this.snapshot.data);
    if (
      data.tenants.some(
        (t) => t.name.toLowerCase() === parsed.data.name.toLowerCase(),
      )
    )
      throw new Error("A tenant with that name already exists.");
    data.tenants.push(parsed.data);
    this.commit(data);
    return parsed.data;
  }

  async loadDemo() {
    const data = structuredClone(this.snapshot.data);
    if (data.demoLoaded) return;
    const demo = createSeed(this.clock());
    if (
      demo.tenants.some((t) =>
        data.tenants.some(
          (existing) =>
            existing.id === t.id ||
            existing.name.toLowerCase() === t.name.toLowerCase(),
        ),
      )
    ) {
      throw new Error(
        "The demo needs the tenant names College and Hospital. One is already in use. Your workspace has not been changed.",
      );
    }
    data.tenants.push(...demo.tenants);
    data.workloads.push(...demo.workloads);
    data.demoLoaded = true;
    this.commit(data);
  }

  async deploy(
    tenantId: TenantId,
    templateId: TemplateId,
    name: string,
  ): Promise<Workload> {
    tenantIdSchema.parse(tenantId);
    templateIdSchema.parse(templateId);
    const data = structuredClone(this.snapshot.data);
    name = name.trim();
    if (!data.tenants.some((t) => t.id === tenantId))
      throw new Error("Select an existing tenant before deploying a workload.");
    if (!/^[a-z][a-z0-9-]{2,39}$/.test(name))
      throw new Error(
        "Use 3–40 lowercase letters, numbers, or hyphens; start with a letter.",
      );
    if (data.workloads.some((w) => w.tenantId === tenantId && w.name === name))
      throw new Error("That workload name already exists in this tenant.");
    if (data.workloads.filter((w) => w.tenantId === tenantId).length >= 12)
      throw new Error(
        "Demo quota reached: 12 workloads per tenant. Delete a workload first.",
      );
    const workload = workloadSchema.parse({
      id: crypto.randomUUID(),
      tenantId,
      templateId,
      name,
      status: "running",
      quarantined: false,
      createdAt: this.clock(),
    });
    data.workloads.push(workload);
    this.commit(data);
    return workload;
  }

  async stop(tenantId: TenantId, id: string, confirmation: string) {
    tenantIdSchema.parse(tenantId);
    const data = structuredClone(this.snapshot.data);
    const workload = this.workload(data, id, tenantId);
    if (confirmation !== workload.name)
      throw new Error("Type the exact workload name to confirm.");
    workload.status = "stopped"; // Does not remove quarantine or incident state.
    this.commit(data);
  }

  async deleteWorkload(tenantId: TenantId, id: string, confirmation: string) {
    tenantIdSchema.parse(tenantId);
    const data = structuredClone(this.snapshot.data);
    if (!data.workloads.some((w) => w.id === id)) return; // Idempotent repeat.
    const workload = this.workload(data, id, tenantId);
    if (confirmation !== workload.name)
      throw new Error("Type the exact workload name to confirm.");
    if (
      data.incidents.some((i) => i.sourceId === id && i.status !== "restored")
    )
      throw new Error(
        "Resolve the active incident before deleting this workload.",
      );
    data.workloads = data.workloads.filter((w) => w.id !== id);
    this.commit(data); // Historical evidence retains names and IDs.
  }

  async simulate(sourceId: string, destinationId: string, port: number) {
    const data = structuredClone(this.snapshot.data);
    const source = this.workload(data, sourceId);
    const destination = this.workload(data, destinationId);
    if (source.id === destination.id)
      throw new Error("Choose two different workloads.");
    if (!Number.isInteger(port) || port < 1 || port > 65535)
      throw new Error("Enter a TCP port from 1 to 65535.");
    const at = this.clock();
    const event = {
      id: crypto.randomUUID(),
      at,
      sourceId,
      destinationId,
      port,
      sourceName: source.name,
      destinationName: destination.name,
      sourceTenant: source.tenantId,
      destinationTenant: destination.tenantId,
      ...decide(source, destination, port),
    };
    data.traffic.push(event);
    const priorResolution = data.incidents.find(
      (i) => i.sourceId === sourceId && i.status === "restored",
    );
    // Use event order rather than timestamps: restore and a new attempt can share a millisecond.
    const resetIndex = data.traffic.findIndex(
      (e) => e.id === priorResolution?.resetAfterEventId,
    );
    // Quarantine denials and unavailable endpoints do not create new alerts.
    const suspicious = data.traffic
      .slice(resetIndex + 1)
      .filter(
        (e) =>
          e.sourceId === sourceId &&
          e.at >= at - WINDOW_MS &&
          e.at <= at &&
          ["cross-tenant", "default-deny"].includes(e.reason),
      );
    const active = data.incidents.find(
      (i) => i.sourceId === sourceId && i.status !== "restored",
    );
    if (!active && suspicious.length >= DENIAL_THRESHOLD) {
      const crossTenant = suspicious.some((e) => e.reason === "cross-tenant");
      const reason = `${suspicious.length} denied attempts within 60 seconds${crossTenant ? ", including cross-tenant access" : " to unapproved destinations"}`;
      const incident: Incident = {
        id: crypto.randomUUID(),
        sourceId,
        sourceName: source.name,
        tenantId: source.tenantId,
        status: "alert",
        reason,
        createdAt: at,
        evidence: suspicious,
        trace: [
          {
            at: suspicious[0].at,
            title: "Connection attempts",
            detail: `${source.name} sent simulated traffic. Source tenant: ${data.tenants.find((t) => t.id === source.tenantId)?.name}.`,
          },
          {
            at,
            title: "Policy decision: denied",
            detail: `${destination.name}:${port} · ${reasonLabels[event.reason]}. See the individual evidence events below.`,
          },
          {
            at,
            title: "Detection: alert raised",
            detail: `${reason}. Threshold: ${DENIAL_THRESHOLD} in a sliding ${WINDOW_MS / 1000}-second window. Awaiting operator quarantine.`,
          },
        ],
      };
      data.incidents.unshift(incident);
    }
    data.traffic = data.traffic.slice(-1000);
    this.commit(data);
    return event;
  }

  private transition(
    incidentId: string,
    expected: Incident["status"],
    next: Incident["status"],
    title: string,
    detail: string,
  ) {
    const data = structuredClone(this.snapshot.data);
    const incident = data.incidents.find((i) => i.id === incidentId);
    if (!incident) throw new Error("Incident not found.");
    if (incident.status === next) return;
    if (incident.status !== expected)
      throw new Error(`This action requires the ${expected} stage.`);
    const workload = this.workload(data, incident.sourceId);
    workload.quarantined = next !== "restored";
    incident.status = next;
    const at = this.clock();
    if (next === "restored") {
      incident.restoredAt = at;
      incident.resetAfterEventId = data.traffic.at(-1)?.id;
    }
    incident.trace.push({ at, title, detail });
    this.commit(data);
  }

  async quarantine(id: string) {
    this.transition(
      id,
      "alert",
      "quarantined",
      "Response: quarantined",
      "Simulated inbound and outbound traffic is now denied, including previously approved access. Dependent services may be disrupted.",
    );
  }
  async review(id: string) {
    this.transition(
      id,
      "quarantined",
      "review",
      "Review started",
      "Operator is reviewing the evidence. Quarantine remains in place until restore.",
    );
  }
  async restore(id: string) {
    this.transition(
      id,
      "review",
      "restored",
      "Response: restored",
      "Quarantine removed. The original static tenant intents apply again. A stopped workload remains stopped.",
    );
  }
}
