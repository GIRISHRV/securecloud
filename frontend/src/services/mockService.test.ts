import { beforeEach, describe, expect, it } from "vitest";
import { MockPortalService, STORAGE_KEY } from "./mockService";
import { createSeed, createEmptyWorkspace } from "../domain/seed";
import type { TemplateId } from "../domain/models";

class MemoryStorage {
  values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}
let storage: MemoryStorage;
let now: number;
let service: MockPortalService;
const data = () => service.getSnapshot().data;
async function raiseAlert() {
  for (let i = 0; i < 3; i++)
    await service.simulate("college-web", "hospital-api", 8080);
  return data().incidents[0].id;
}
beforeEach(async () => {
  storage = new MemoryStorage();
  now = 1_000_000;
  service = new MockPortalService(storage, () => now);
  await service.loadDemo();
});

describe("static policy and detection", () => {
  it("allows only the directed, tenant-local intent on its exact port", async () => {
    expect(
      (await service.simulate("college-web", "college-api", 8080)).decision,
    ).toBe("allowed");
    expect(
      (await service.simulate("hospital-api", "hospital-database", 5432))
        .decision,
    ).toBe("allowed");
    expect(
      (await service.simulate("college-api", "college-web", 80)).reason,
    ).toBe("default-deny");
    expect(
      (await service.simulate("college-web", "college-api", 443)).reason,
    ).toBe("default-deny");
    expect(
      (await service.simulate("college-web", "hospital-api", 8080)).reason,
    ).toBe("cross-tenant");
  });
  it("alerts at three suspicious denials and preserves a complete triggering trace", async () => {
    await service.simulate("college-web", "hospital-api", 8080);
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(0);
    await service.simulate("college-web", "hospital-api", 8080);
    const incident = data().incidents[0];
    expect(incident.status).toBe("alert");
    expect(incident.reason).toContain("3 denied attempts within 60 seconds");
    expect(incident.evidence).toHaveLength(3);
    expect(incident.evidence[0].destinationName).toBe("hospital-api");
    expect(incident.trace.map((s) => s.title)).toEqual([
      "Connection attempts",
      "Policy decision: denied",
      "Detection: alert raised",
    ]);
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(1);
  });
  it("expires attempts outside the sliding window", async () => {
    await service.simulate("college-web", "hospital-api", 8080);
    await service.simulate("college-web", "hospital-api", 8080);
    now += 60_001;
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(0);
    await service.simulate("college-web", "hospital-api", 8080);
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(1);
  });
  it("counts the inclusive window boundary and does not mix sources", async () => {
    await service.simulate("college-web", "hospital-api", 8080);
    await service.simulate("hospital-web", "college-api", 8080);
    now += 60_000;
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(0);
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(1);
  });
  it("does not alert on allowed or unavailable traffic", async () => {
    for (let i = 0; i < 4; i++)
      await service.simulate("college-web", "college-api", 8080);
    await service.stop("hospital", "hospital-api", "hospital-api");
    for (let i = 0; i < 4; i++)
      expect(
        (await service.simulate("college-web", "hospital-api", 8080)).decision,
      ).toBe("inconclusive");
    expect(data().incidents).toHaveLength(0);
  });
  it("rejects invalid endpoints and ports without changing state", async () => {
    const original = data();
    await expect(
      service.simulate("missing", "college-api", 8080),
    ).rejects.toThrow();
    await expect(
      service.simulate("college-web", "college-web", 8080),
    ).rejects.toThrow();
    for (const port of [0, 65536, 2.5, NaN])
      await expect(
        service.simulate("college-web", "college-api", port),
      ).rejects.toThrow();
    expect(data()).toBe(original);
  });
});

describe("containment and recovery", () => {
  it("withdraws previously allowed access, survives refresh, and restores the same policy", async () => {
    const baseline = await service.simulate("college-web", "college-api", 8080);
    const id = await raiseAlert();
    await service.quarantine(id);
    service = new MockPortalService(storage, () => now);
    expect(
      (await service.simulate("college-web", "college-api", 8080)).reason,
    ).toBe("quarantine");
    expect(
      (await service.simulate("hospital-web", "hospital-api", 8080)).decision,
    ).toBe("allowed");
    await expect(service.restore(id)).rejects.toThrow("review");
    await service.review(id);
    expect(
      (await service.simulate("college-web", "college-api", 8080)).reason,
    ).toBe("quarantine");
    await service.restore(id);
    expect(
      (await service.simulate("college-web", "college-api", 8080)).decision,
    ).toBe(baseline.decision);
    expect(data().incidents[0].trace).toHaveLength(6);
    expect(data().incidents[0].status).toBe("restored");
    expect(
      (await service.simulate("college-web", "hospital-api", 8080)).reason,
    ).toBe("cross-tenant");
    expect(data().incidents).toHaveLength(1);
    // Fresh attempts at the same clock tick must still count after restore.
    await service.simulate("college-web", "hospital-api", 8080);
    await service.simulate("college-web", "hospital-api", 8080);
    expect(data().incidents).toHaveLength(2);
  });
  it("blocks incoming approved access too, and stopping never clears quarantine", async () => {
    for (let i = 0; i < 3; i++)
      await service.simulate("college-api", "hospital-database", 5432);
    const id = data().incidents[0].id;
    await service.quarantine(id);
    expect(
      (await service.simulate("college-web", "college-api", 8080)).reason,
    ).toBe("quarantine");
    await service.stop("college", "college-api", "college-api");
    expect(
      data().workloads.find((w) => w.id === "college-api")?.quarantined,
    ).toBe(true);
    expect(
      (await service.simulate("college-web", "college-api", 8080)).decision,
    ).toBe("inconclusive");
    await service.review(id);
    await service.restore(id);
    expect(data().workloads.find((w) => w.id === "college-api")?.status).toBe(
      "stopped",
    );
  });
  it("keeps transition retries idempotent and prevents skipping stages", async () => {
    const id = await raiseAlert();
    await expect(service.review(id)).rejects.toThrow();
    await service.quarantine(id);
    await service.quarantine(id);
    expect(data().incidents[0].trace).toHaveLength(4);
    await service.review(id);
    await service.review(id);
    await service.restore(id);
    await service.restore(id);
    expect(data().incidents[0].trace).toHaveLength(6);
  });
});

describe("lifecycle and storage", () => {
  it("deploys allowlisted templates with validated unique names and tenant bounds", async () => {
    const deployed = await service.deploy("college", "web", "new-website");
    expect(data().workloads).toHaveLength(7);
    expect(
      (await service.simulate(deployed.id, "college-api", 8080)).decision,
    ).toBe("allowed");
    await expect(
      service.deploy("college", "web", "new-website"),
    ).rejects.toThrow("already exists");
    await expect(
      service.deploy("college", "shell" as TemplateId, "bad-image"),
    ).rejects.toThrow();
    for (const name of [
      "",
      "a",
      "UPPERCASE",
      "bad name",
      "<script>",
      "a".repeat(41),
    ])
      await expect(service.deploy("college", "web", name)).rejects.toThrow();
    await service.deploy("hospital", "web", "new-website");
    for (let i = 0; i < 8; i++)
      await service.deploy("college", "api", `new-api-${i}`);
    await expect(
      service.deploy("college", "api", "over-quota"),
    ).rejects.toThrow("quota");
  });
  it("requires exact-name and tenant match for stop/delete, and accepts retries", async () => {
    await expect(
      service.stop("hospital", "college-web", "college-web"),
    ).rejects.toThrow();
    await expect(
      service.stop("college", "college-web", "wrong"),
    ).rejects.toThrow();
    await expect(
      service.deleteWorkload("hospital", "college-web", "college-web"),
    ).rejects.toThrow();
    await expect(
      service.deleteWorkload("college", "college-web", "wrong"),
    ).rejects.toThrow();
    await service.stop("college", "college-web", "college-web");
    await service.stop("college", "college-web", "college-web");
    expect(data().workloads[0].status).toBe("stopped");
    await service.deleteWorkload("college", "college-web", "college-web");
    await service.deleteWorkload("college", "college-web", "college-web");
    expect(data().workloads).toHaveLength(5);
  });
  it("blocks deletion while an incident is active and keeps historical evidence after deletion", async () => {
    const id = await raiseAlert();
    await expect(
      service.deleteWorkload("college", "college-web", "college-web"),
    ).rejects.toThrow("active incident");
    await service.quarantine(id);
    await service.review(id);
    await service.restore(id);
    await service.deleteWorkload("college", "college-web", "college-web");
    service = new MockPortalService(storage, () => now);
    expect(data().incidents[0].evidence[0].sourceName).toBe("college-web");
    expect(data().workloads).toHaveLength(5);
  });
  it("preserves changes on reload and reset touches only its own storage key", async () => {
    storage.setItem("unrelated", "keep");
    await service.deploy("college", "web", "persisted-web");
    await raiseAlert();
    service = new MockPortalService(storage, () => now);
    expect(data().workloads).toHaveLength(7);
    expect(data().incidents).toHaveLength(1);
    await service.reset();
    expect(data()).toEqual(createEmptyWorkspace());
    expect(storage.getItem("unrelated")).toBe("keep");
    expect(
      new MockPortalService(storage).getSnapshot().data.workloads,
    ).toHaveLength(0);
  });
  it("recovers from malformed saved data and inconsistent quarantine without crashing", () => {
    for (const bad of [
      "not json",
      "{}",
      JSON.stringify({ ...createSeed(now), version: 9 }),
      JSON.stringify({ ...createSeed(now), workloads: [{ bad: true }] }),
    ]) {
      storage.setItem(STORAGE_KEY, bad);
      const snapshot = new MockPortalService(storage).getSnapshot();
      expect(snapshot.data.workloads).toHaveLength(0);
      expect(snapshot.storageWarning).toContain("could not be loaded");
    }
    const inconsistent = createSeed(now);
    inconsistent.workloads[0].quarantined = true;
    storage.setItem(STORAGE_KEY, JSON.stringify(inconsistent));
    expect(
      new MockPortalService(storage).getSnapshot().storageWarning,
    ).toBeTruthy();
  });
  it("remains usable and warns when persistence is blocked", async () => {
    service = new MockPortalService({
      getItem: () => {
        throw Error("blocked");
      },
      setItem: () => {
        throw Error("full");
      },
    });
    const tenant = await service.createTenant("Research", "");
    await service.deploy(tenant.id, "web", "memory-only");
    expect(data().workloads).toHaveLength(1);
    expect(service.getSnapshot().storageWarning).toContain("memory only");
  });
});

describe("empty workspace and dynamic tenants", () => {
  it("starts empty, does not import the old automatically seeded session, and loads demo only on request", async () => {
    const clean = new MemoryStorage();
    clean.setItem("securecloud:demo:v1", "legacy-data");
    const portal = new MockPortalService(clean);
    expect(portal.getSnapshot().data).toEqual(createEmptyWorkspace());
    await portal.loadDemo();
    expect(portal.getSnapshot().data.tenants).toHaveLength(2);
    expect(portal.getSnapshot().data.workloads).toHaveLength(6);
    expect(clean.getItem("securecloud:demo:v1")).toBe("legacy-data");
  });
  it("adds demo data without replacing custom resources and never duplicates or revives demo resources", async () => {
    await service.reset();
    const tenant = await service.createTenant("Research", "Team workspace");
    const workload = await service.deploy(tenant.id, "web", "research-web");
    await service.loadDemo();
    expect(data().tenants).toHaveLength(3);
    expect(data().workloads.find((w) => w.id === workload.id)).toEqual(
      workload,
    );
    await service.stop("college", "college-web", "college-web");
    await service.loadDemo();
    expect(data().workloads).toHaveLength(7);
    expect(data().workloads.find((w) => w.id === "college-web")?.status).toBe(
      "stopped",
    );
    service = new MockPortalService(storage);
    expect(data().tenants).toHaveLength(3);
    expect(data().demoLoaded).toBe(true);
  });
  it("applies the same policy and containment flow to an arbitrary third tenant", async () => {
    const tenant = await service.createTenant("Research & Development", "");
    const web = await service.deploy(tenant.id, "web", "research-web");
    const api = await service.deploy(tenant.id, "api", "research-api");
    expect((await service.simulate(web.id, api.id, 8080)).decision).toBe(
      "allowed",
    );
    for (let i = 0; i < 3; i++)
      expect((await service.simulate(web.id, "college-api", 8080)).reason).toBe(
        "cross-tenant",
      );
    const incident = data().incidents[0];
    expect(incident.tenantId).toBe(tenant.id);
    await service.quarantine(incident.id);
    expect((await service.simulate(web.id, api.id, 8080)).reason).toBe(
      "quarantine",
    );
    await service.review(incident.id);
    await service.restore(incident.id);
    expect((await service.simulate(web.id, api.id, 8080)).decision).toBe(
      "allowed",
    );
  });
  it("persists more than two tenants and more than the old 24-workload total", async () => {
    await service.reset();
    for (const name of ["Research", "Finance", "Operations"]) {
      const tenant = await service.createTenant(name, "");
      for (let i = 0; i < 9; i++)
        await service.deploy(tenant.id, "web", `web-${i}`);
    }
    service = new MockPortalService(storage);
    expect(data().tenants).toHaveLength(3);
    expect(data().workloads).toHaveLength(27);
    expect(service.getSnapshot().storageWarning).toBeNull();
  });
  it("validates tenant creation and rejects unknown deployment tenants", async () => {
    await service.createTenant("  Research  ", "");
    await expect(service.createTenant("research", "")).rejects.toThrow(
      "already exists",
    );
    for (const name of ["", " ", "x", "x".repeat(61)])
      await expect(service.createTenant(name, "")).rejects.toThrow();
    await expect(
      service.createTenant("Finance", "x".repeat(161)),
    ).rejects.toThrow();
    await expect(
      service.deploy("missing-tenant", "web", "web-one"),
    ).rejects.toThrow("existing tenant");
    const corrupted = structuredClone(data());
    corrupted.workloads[0].tenantId = "missing-tenant";
    storage.setItem(STORAGE_KEY, JSON.stringify(corrupted));
    expect(new MockPortalService(storage).getSnapshot().data).toEqual(
      createEmptyWorkspace(),
    );
  });
  it("rejects demo-name collisions without partial changes", async () => {
    await service.reset();
    await service.createTenant("College", "Custom tenant");
    const before = data();
    await expect(service.loadDemo()).rejects.toThrow("already in use");
    expect(data()).toBe(before);
  });
});
