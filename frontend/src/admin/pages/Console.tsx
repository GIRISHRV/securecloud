import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, FileCode2, Lock, Pause, Play, ShieldCheck, Trash2, X } from "lucide-react";
import type { Advice, AdminIncident, AdminService, AdminSnapshot, PlatformService, Posture, ProviderShop, Usage } from "../adminService";
import { AreaChart } from "../charts";
import { Drawer, Empty, FilterInput, PageHead, Panel, relative, Status, Tabs } from "../ui";
import {
  ago, downloadEvidence, IncidentDetail, KIND, nameOf, RiskBars, ServiceDetail, statusOf, summary, useIncidentActions, useNow, WINDOW,
} from "./Security";
import { errorText, useToaster } from "../toast";
import "../console.css";

/*
 * Provider console pages beyond the overview. Every view is built from API records only:
 * incidents and findings, Hubble flow evidence, workloads and their approved intents.
 */

type Traffic = AdminSnapshot["security"]["traffic"];

function usePlatformServices(service: AdminService, enabled = true) {
  const [items, setItems] = useState<PlatformService[] | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const load = () => service.platformServices().then((value) => { if (active) setItems(value); }).catch(() => undefined);
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [service, enabled]);
  return items;
}

const isOpen = (item: AdminIncident) => !["restored", "closed"].includes(item.status);

/* ----------------------------------------------------------------------------- Alerts */

type AlertFilter = "open" | "isolated" | "closed" | "all";

export function Alerts({ data, service, refresh }: { data: AdminSnapshot; service: AdminService; refresh: () => Promise<void> }) {
  const incidents = useMemo(() => data.security.incidents.slice().sort((a, b) => Number(isOpen(b)) - Number(isOpen(a)) || b.createdAt - a.createdAt), [data.security.incidents]);
  const [filter, setFilter] = useState<AlertFilter>("open");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { busy, respond } = useIncidentActions(service, refresh);

  const groups: Record<AlertFilter, AdminIncident[]> = {
    open: incidents.filter((item) => item.status === "alert"),
    isolated: incidents.filter((item) => item.status === "quarantined" || item.status === "review"),
    closed: incidents.filter((item) => !isOpen(item)),
    all: incidents,
  };
  const list = groups[filter];
  const selected = list.find((item) => item.id === selectedId) ?? list[0] ?? null;
  const series = useMemo(() => data.security.risk
    .filter((item) => item.sourceName === selected?.sourceName)
    .sort((a, b) => a.windowEnd - b.windowEnd).slice(-40), [data.security.risk, selected?.sourceName]);

  return (
    <>
      <PageHead title="Alerts" description="Every incident the AI raised, and what was done about it." />
      <Tabs label="Filter alerts" value={filter} onChange={setFilter} options={[
        { id: "open", label: "Needs a decision", count: groups.open.length },
        { id: "isolated", label: "Locked out", count: groups.isolated.length },
        { id: "closed", label: "Resolved", count: groups.closed.length },
        { id: "all", label: "All", count: groups.all.length },
      ]} />
      {!selected
        ? <Panel><Empty title={filter === "open" ? "Nothing needs a decision" : "Nothing here"}>Alerts appear when the AI flags a service.</Empty></Panel>
        : <div className="cn-split">
            <Panel flush>
              <ul className="ad-incident-list">
                {list.map((item) => (
                  <li key={item.id}>
                    <button className={item.id === selected.id ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                      <span><strong>{nameOf(item.sourceName)}</strong><small>{relative(item.createdAt)}</small></span>
                      <Status {...statusOf(item.status)} />
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <div className="cn-detail">
              <IncidentDetail incident={selected} busy={busy} respond={async (action) => { respond(selected, action); }} onEvidence={() => void downloadEvidence(service, selected.id)} />
              {series.length > 1 && (
                <Panel title="Risk over time" subtitle={nameOf(selected.sourceName)}>
                  <AreaChart ariaLabel="Risk over time" format={(value) => `${Math.round(value * 100)}%`} fixedMax={1} height={180}
                    threshold={{ value: series[series.length - 1].threshold, label: "alert level" }}
                    points={series.map((item) => ({
                      label: new Date(item.windowEnd * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
                      value: item.accumulatedRisk, detail: `${nameOf(item.sourceName)} → ${nameOf(item.destinationName)}`,
                    }))} />
                </Panel>
              )}
            </div>
          </div>}
    </>
  );
}

/* ---------------------------------------------------------------------------- Traffic */

type TrafficFilter = "all" | "allowed" | "denied";

export function TrafficPage({ data, services }: { data: AdminSnapshot; services: PlatformService[] | null }) {
  const now = useNow(5000);
  const [filter, setFilter] = useState<TrafficFilter>("all");
  const [query, setQuery] = useState("");
  const tenants = new Map((services ?? []).map((item) => [item.name, item.tenant]));
  // Approved routes, so a drop on one of them can be shown as a lock-out rather than "not allowed".
  const approved = new Set((services ?? []).flatMap((item) => item.calls.map((call) => `${item.name}>${call}`)));
  const traffic = data.security.traffic.slice().sort((a, b) => b.at - a.at);
  const counts = { all: traffic.length, allowed: traffic.filter((t) => t.decision === "allowed").length, denied: traffic.filter((t) => t.decision === "denied").length };
  const needle = query.trim().toLowerCase();
  const rows = traffic.filter((item) => (filter === "all" || item.decision === filter)
    && (!needle || `${nameOf(item.sourceName)} ${nameOf(item.destinationName)} ${item.port}`.toLowerCase().includes(needle)));

  return (
    <>
      <PageHead title="Traffic" description="Latest Hubble record for each service-to-service route.">
        <FilterInput value={query} onChange={setQuery} label="Find a service" />
      </PageHead>
      <Tabs label="Filter traffic" value={filter} onChange={setFilter} options={[
        { id: "all", label: "All", count: counts.all },
        { id: "allowed", label: "Allowed", count: counts.allowed },
        { id: "denied", label: "Blocked", count: counts.denied },
      ]} />
      <Panel flush>
        {rows.length
          ? <div className="ad-table-wrap"><table className="ad-table cn-table">
              <thead><tr><th>Result</th><th>From</th><th>To</th><th>Port</th><th>Why</th><th>When</th></tr></thead>
              <tbody>{rows.map((item) => {
                const crossing = item.reason === "cross-tenant";
                return (
                  <tr key={item.id}>
                    <td><Status value={item.decision} label={item.decision === "denied" ? "Blocked" : item.decision === "allowed" ? "Allowed" : "Unknown"} /></td>
                    <td><strong>{nameOf(item.sourceName)}</strong><small>{tenants.get(item.sourceName) ?? ""}</small></td>
                    <td><strong>{nameOf(item.destinationName)}</strong><small>{item.destinationName ? tenants.get(item.destinationName) ?? "" : "outside"}</small></td>
                    <td><code>{item.port}</code></td>
                    <td>{crossing ? <span className="cn-tag bad">Crossed a tenant wall</span>
                      : item.reason === "quarantine" || (item.decision === "denied" && approved.has(`${item.sourceName}>${item.destinationName}`))
                        ? <span className="cn-tag warn">Blocked by a lock-out</span>
                      : item.reason === "default-deny" ? <span className="cn-tag bad">Not on the allow-list</span>
                      : <span className="cn-tag good">Approved route</span>}</td>
                    <td className="ad-muted">{ago(now, item.at)}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          : <Empty title="No traffic matches">Try another filter.</Empty>}
      </Panel>
    </>
  );
}

/* -------------------------------------------------------------------------- Workloads */

export function Workloads({ data, services }: { data: AdminSnapshot; services: PlatformService[] | null }) {
  const now = useNow(5000);
  const [selected, setSelected] = useState<string | null>(null);
  const traffic = data.security.traffic.filter((item) => item.at >= now - WINDOW);
  const peak = new Map<string, number>();
  for (const item of data.security.risk) peak.set(item.sourceName, Math.max(peak.get(item.sourceName) ?? 0, item.accumulatedRisk));
  const tenants = [...new Set((services ?? []).map((item) => item.tenant))];
  const underAlert = new Set(data.security.incidents.filter((incident) => incident.status === "alert").map((incident) => incident.sourceName));
  const item = (services ?? []).find((service) => service.name === selected) ?? null;

  return (
    <>
      <PageHead title="Workloads" description="Every service on the platform, who owns it and how it is behaving." />
      {!services
        ? <Panel><Empty title="Loading workloads" /></Panel>
        : <div className="cn-tenants">
            {tenants.map((tenant) => {
              const rows = services.filter((service) => service.tenant === tenant);
              return (
                <Panel key={tenant} title={tenant} subtitle={`${rows.length} service${rows.length === 1 ? "" : "s"}`} flush>
                  <ul className="cn-workloads">
                    {rows.map((service) => {
                      const blocked = traffic.filter((t) => t.sourceName === service.name && t.decision === "denied").length;
                      const risk = peak.get(service.name) ?? 0;
                      return (
                        <li key={service.id}>
                          <button onClick={() => setSelected(service.name)}>
                            <span className={`cn-dot ${service.quarantined ? "bad" : underAlert.has(service.name) ? "warn" : service.status === "running" ? "good" : "idle"}`} aria-hidden="true" />
                            <span className="cn-wl-name"><strong>{nameOf(service.name)}</strong><small>{KIND[service.kind]}</small></span>
                            <span className="cn-wl-stat">{service.quarantined ? <span className="cn-tag bad"><Lock size={12} />Locked out</span>
                              : underAlert.has(service.name) ? <span className="cn-tag warn"><AlertTriangle size={12} />Open alert</span>
                              : blocked ? <span className="cn-tag bad">{blocked} blocked route{blocked === 1 ? "" : "s"}</span> : <span className="cn-tag good">No issues</span>}</span>
                            <span className="cn-wl-risk" title="Peak AI risk"><i><b style={{ width: `${risk * 100}%` }} className={risk >= 0.5 ? "high" : ""} /></i>{Math.round(risk * 100)}%</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </Panel>
              );
            })}
            <Panel title="AI risk" subtitle="Peak score per service">
              <RiskBars risk={data.security.risk} />
            </Panel>
          </div>}
      <Drawer open={Boolean(selected)} title={nameOf(selected)} subtitle={item ? `${item.tenant} · ${KIND[item.kind]}` : "Service"} onClose={() => setSelected(null)}>
        {selected && <ServiceDetail name={selected} item={item} traffic={traffic} now={now} />}
      </Drawer>
    </>
  );
}

/* ---------------------------------------------------------------------- Network policy */

export function Policies({ data, services, service }: { data: AdminSnapshot; services: PlatformService[] | null; service: AdminService }) {
  const now = useNow(10_000);
  const list = useMemo(() => (services ?? []).slice().sort((a, b) => a.tenant.localeCompare(b.tenant) || a.name.localeCompare(b.name)), [services]);
  const blocked = new Map<string, number>();
  for (const item of data.security.traffic as Traffic) {
    if (item.decision !== "denied" || item.at < now - WINDOW) continue;
    const key = `${item.sourceName}>${item.destinationName ?? "internet"}`;
    blocked.set(key, (blocked.get(key) ?? 0) + 1);
  }
  const allowedRoutes = list.reduce((sum, item) => sum + item.calls.length, 0);
  const columns = [...list.map((item) => item.name), "internet"];

  return (
    <>
      <PageHead title="Network policy" description="The allow-list each service runs under. Anything not ticked is denied by default." />
      <div className="cn-policy-stats">
        <div><strong>{allowedRoutes}</strong><span>approved routes</span></div>
        <div><strong>{list.length * (columns.length - 1) - allowedRoutes}</strong><span>routes denied by default</span></div>
        <div className={blocked.size ? "bad" : ""}><strong>{blocked.size}</strong><span>denied routes tried in the last 15 min</span></div>
      </div>
      <Panel flush>
        {!list.length
          ? <Empty title="Loading policy" />
          : <div className="cn-matrix-wrap">
              <table className="cn-matrix">
                <thead>
                  <tr><th className="corner">From ↓ · To →</th>{columns.map((name) => <th key={name}><span>{name === "internet" ? "Internet" : nameOf(name)}</span></th>)}</tr>
                </thead>
                <tbody>
                  {list.map((source) => (
                    <tr key={source.id}>
                      <th><strong>{nameOf(source.name)}</strong><small>{source.tenant}</small></th>
                      {columns.map((target) => {
                        if (target === source.name) return <td key={target} className="self" />;
                        const allowed = source.calls.includes(target);
                        const tried = blocked.get(`${source.name}>${target}`) ?? 0;
                        // An approved route can still be dropped while one end is locked out.
                        const state = allowed ? (tried ? "locked" : "allow") : tried ? "tried" : "deny";
                        const label = { allow: "approved", locked: "approved, but blocked while a service is locked out", tried: "denied, and it was tried", deny: "denied by default" }[state];
                        return (
                          <td key={target} className={state} title={`${nameOf(source.name)} → ${target === "internet" ? "Internet" : nameOf(target)}: ${label}`}>
                            {state === "allow" ? <Check size={14} aria-label={label} /> : state === "locked" ? <Lock size={13} aria-label={label} />
                              : state === "tried" ? <X size={14} aria-label={label} /> : <i aria-hidden="true" />}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>}
      </Panel>
      <div className="cn-legend">
        <span><b className="allow"><Check size={12} /></b>Approved</span>
        <span><b className="tried"><X size={12} /></b>Denied and tried recently</span>
        <span><b className="locked"><Lock size={11} /></b>Approved, blocked by a lock-out</span>
        <span><b className="deny"><i /></b>Denied by default</span>
        <span className="ad-muted">Policy: Kubernetes NetworkPolicy, default-deny per tenant, enforced by Cilium.</span>
      </div>
      <PolicyAdvisor service={service} />
    </>
  );
}

export { usePlatformServices, summary };

/* ------------------------------------------------------------------------------ Shops */

const SHOP_STATE: Record<string, { value: string; label: string }> = {
  live: { value: "online", label: "Live" }, provisioning: { value: "processing", label: "Opening" },
  failed: { value: "failed", label: "Failed" }, removing: { value: "review", label: "Removing" },
  pausing: { value: "review", label: "Pausing" }, paused: { value: "neutral", label: "Paused" }, resuming: { value: "processing", label: "Resuming" },
};
const MODES = [
  { id: "learn", label: "Learn", hint: "Watch and learn normal traffic. No alerts yet." },
  { id: "monitor", label: "Monitor", hint: "Raise alerts. A person decides." },
  { id: "protect", label: "Protect", hint: "Isolate corroborated attacks automatically." },
] as const;

type ShopAction = { kind: "remove" | "pause" | "resume" | "posture" | "policies"; shop: ProviderShop };

function quotaBar(usage: Usage | undefined, key: string) {
  const entry = usage?.[key];
  if (!entry) return null;
  const parse = (value: string) => value.endsWith("m") ? Number(value.slice(0, -1)) / 1000 : value.endsWith("Mi") ? Number(value.slice(0, -2)) / 1024 : value.endsWith("Gi") ? Number(value.slice(0, -2)) : Number(value);
  const ratio = Math.min(1, parse(entry.used) / Math.max(parse(entry.hard), 0.0001));
  return <span className="cn-quota" title={`${key}: ${entry.used} of ${entry.hard}`}><i><b style={{ width: `${ratio * 100}%` }} className={ratio > 0.8 ? "high" : ""} /></i>{entry.used}/{entry.hard}</span>;
}

export function Shops({ service }: { service: AdminService }) {
  const [data, setData] = useState<{ items: ProviderShop[]; quota: { used: number; limit: number } } | null>(null);
  const [usage, setUsage] = useState<Record<string, Usage>>({});
  const [action, setAction] = useState<ShopAction | null>(null);
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [posture, setPosture] = useState<Posture | null>(null);
  const [yaml, setYaml] = useState("");
  const toaster = useToaster();
  const load = useMemo(() => () => service.providerShops().then((value) => {
    setData(value);
    for (const shop of value.items) service.shopUsage(shop.slug).then((u) => setUsage((all) => ({ ...all, [shop.slug]: u }))).catch(() => undefined);
  }).catch(() => undefined), [service]);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [load]);

  function open(next: ShopAction) {
    setAction(next); setConfirm(""); setError(""); setPosture(null); setYaml("");
    if (next.kind === "posture") service.shopPosture(next.shop.slug).then(setPosture).catch((reason) => setError(errorText(reason, "Could not read the cluster")));
    if (next.kind === "policies") service.shopPolicies(next.shop.slug).then((value) => setYaml(value.yaml)).catch((reason) => setError(errorText(reason, "Could not read the cluster")));
  }

  async function setMode(shop: ProviderShop, mode: "learn" | "monitor" | "protect") {
    try { await service.setShopMode(shop.slug, mode); await load(); }
    catch (reason) { toaster.show(() => Promise.reject(reason), { loading: "", success: "", error: ["Could not change the mode", errorText(reason, "Try again")] }); }
  }

  async function run() {
    if (!action || !["remove", "pause", "resume"].includes(action.kind)) return;
    setBusy(true); setError("");
    try {
      if (action.kind === "remove") await service.removeShop(action.shop.slug, confirm);
      else await service.shopLifecycle(action.shop.slug, action.kind as "pause" | "resume", confirm);
      setAction(null); await load();
    } catch (reason) { setError(errorText(reason, "That did not work")); }
    finally { setBusy(false); }
  }

  const confirmable = action && ["remove", "pause", "resume"].includes(action.kind);
  const titles: Record<ShopAction["kind"], string> = { remove: "Remove", pause: "Pause", resume: "Resume", posture: "Security posture", policies: "Live network policies" };
  return (
    <>
      <PageHead title="Shops" description="Every shop on the platform, each in its own isolated tenant." />
      {data && (
        <div className="cn-policy-stats">
          <div><strong>{data.items.length}</strong><span>shops on the platform</span></div>
          <div><strong>{data.quota.used}<small className="cn-of"> / {data.quota.limit}</small></strong><span>lab quota in use</span></div>
          <div><strong>{data.items.filter((shop) => shop.mode === "protect").length}</strong><span>in Protect mode</span></div>
        </div>
      )}
      <Panel flush>
        {!data ? <Empty title="Loading shops" /> : (
          <div className="ad-table-wrap"><table className="ad-table cn-table">
            <thead><tr><th>Shop</th><th>Owner</th><th>Status</th><th>Security mode</th><th>Space used</th><th aria-label="Actions" /></tr></thead>
            <tbody>{data.items.map((shop) => (
              <tr key={shop.slug}>
                <td><strong>{shop.name}</strong><small><a href={`/${shop.slug}/shop`} target="_blank" rel="noreferrer">/{shop.slug}/shop</a></small></td>
                <td>{shop.fixed ? <span className="ad-muted">Testbed shop</span> : <><strong>{shop.owner?.display_name ?? "Unknown"}</strong><small>{shop.owner?.email}{shop.staff ? ` · +${shop.staff} staff` : ""}</small></>}</td>
                <td><Status {...(SHOP_STATE[shop.state] ?? { value: "neutral", label: shop.state })} /><small className="ad-muted">{relative(shop.created_at)}</small></td>
                <td>
                  <div className="ad-segment cn-modes" role="group" aria-label={`Security mode for ${shop.name}`}>
                    {MODES.map((mode) => (
                      <button key={mode.id} title={mode.hint} className={shop.mode === mode.id ? `active ${mode.id}` : ""} aria-pressed={shop.mode === mode.id}
                        onClick={() => void setMode(shop, mode.id)}>{mode.label}</button>
                    ))}
                  </div>
                  {shop.mode === "learn" && shop.mode_auto && <small className="ad-muted">Moves to Monitor after 10 min</small>}
                </td>
                <td>{quotaBar(usage[shop.slug], "pods")}{quotaBar(usage[shop.slug], "requests.memory")}</td>
                <td className="cn-actions">
                  <button className="ad-button" onClick={() => open({ kind: "posture", shop })}><ShieldCheck size={14} />Posture</button>
                  <button className="ad-button" onClick={() => open({ kind: "policies", shop })}><FileCode2 size={14} />Policies</button>
                  {!shop.fixed && (shop.state === "paused"
                    ? <button className="ad-button" onClick={() => open({ kind: "resume", shop })}><Play size={14} />Resume</button>
                    : <button className="ad-button" disabled={shop.state !== "live"} onClick={() => open({ kind: "pause", shop })}><Pause size={14} />Pause</button>)}
                  {shop.fixed
                    ? <span className="ad-muted" title="The attack testbed depends on this shop">Protected</span>
                    : <button className="ad-button" disabled={["removing", "pausing", "resuming"].includes(shop.state)} onClick={() => open({ kind: "remove", shop })}><Trash2 size={14} />Remove</button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Panel>
      <Drawer open={Boolean(action)} title={action ? `${titles[action.kind]}${confirmable ? ` ${action.shop.name}?` : ` · ${action.shop.name}`}` : ""}
        subtitle={action?.kind === "remove" ? "This deletes the shop's namespace and everything in it."
          : action?.kind === "pause" ? "Scales the shop to zero. Its data and security labels stay." : action?.kind === "resume" ? "Starts the shop's services again."
          : action?.kind === "posture" ? "Live checks against CIS Kubernetes Benchmark and NSA-CISA hardening guidance." : "Read back from Kubernetes, exactly as enforced."}
        onClose={() => setAction(null)}
        footer={confirmable ? <><button className="ad-button" onClick={() => setAction(null)}>Cancel</button>
          <button className={`ad-button ${action?.kind === "remove" ? "cn-danger" : "ad-button-primary"}`} disabled={busy || confirm !== action?.shop.slug} onClick={() => void run()}>
            {busy ? "Working…" : titles[action!.kind]}</button></> : undefined}>
        {action && confirmable && (
          <div className="ov-service">
            {action.kind === "remove" && <ul className="cn-remove">
              <li>The storefront, order system and database are deleted from the cluster.</li>
              <li>The owner loses access, and the lab quota is freed.</li>
              <li>The audit log keeps a record. Shops with a locked-out workload can't be removed.</li>
            </ul>}
            <label className="cn-confirm">Type <code>{action.shop.slug}</code> to confirm
              <input value={confirm} onChange={(event) => setConfirm(event.target.value.trim())} autoFocus spellCheck={false} />
            </label>
          </div>
        )}
        {action?.kind === "posture" && (posture
          ? <div className="cn-posture">
              <p className="cn-score"><strong>{Math.round((posture.score ?? 0) * 100)}%</strong> {posture.passed} of {posture.total} checks pass</p>
              <ul>{posture.checks.map((check) => (
                <li key={check.id} className={check.passed ? "pass" : "fail"}>
                  {check.passed ? <Check size={15} /> : <X size={15} />}
                  <div><strong>{check.title}</strong><small>{check.refs.join(" · ")}{check.failing.length ? ` · fails: ${check.failing.join(", ")}` : ""}</small></div>
                </li>))}</ul>
              <p className="ad-muted">A focused set of checks, not a full benchmark scan.</p>
            </div>
          : !error && <Empty title="Reading the cluster…" />)}
        {action?.kind === "policies" && (yaml ? <pre className="cn-yaml">{yaml}</pre> : !error && <Empty title="Reading the cluster…" />)}
        {error && <p className="ad-inline-error" role="alert">{error}</p>}
      </Drawer>
    </>
  );
}

/* --------------------------------------------------------------------- Policy advisor */

export function PolicyAdvisor({ service }: { service: AdminService }) {
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => { service.policyAdvice().then(setAdvice).catch(() => undefined); }, [service]);
  if (!advice) return <Panel title="Policy advisor"><Empty title="Reading recent flows…" /></Panel>;
  return (
    <Panel title="Policy advisor" subtitle={`Least-privilege review of the last ${Math.round(advice.window_seconds / 60)} minutes. Suggestions only: nothing is applied.`}>
      <div className="cn-advice">
        <section>
          <h3>Blocked paths</h3>
          {advice.blocked_paths.length ? <ul>{advice.blocked_paths.map((item) => {
            const key = `${item.source}>${item.destination}:${item.port}`;
            return (
              <li key={key}>
                <div><strong>{nameOf(item.source)} → {item.destination === "outside the cluster" ? item.destination : nameOf(item.destination)}</strong>
                  <small>port {item.port ?? "?"} · {item.attempts} attempt{item.attempts === 1 ? "" : "s"}{item.cross_tenant ? " · crosses a tenant wall" : ""}{item.suspicious_source ? " · source is under an alert" : ""}</small></div>
                {item.recommendation === "keep-blocked"
                  ? <span className="cn-tag good">Keep blocked</span>
                  : <button className="cn-tag warn" onClick={() => setOpen(open === key ? null : key)}>Review{item.draft ? " · draft" : ""}</button>}
                {open === key && item.draft && <pre className="cn-yaml">{item.draft}</pre>}
              </li>);
          })}</ul> : <p className="ad-muted">Nothing was blocked in this window.</p>}
        </section>
        <section>
          <h3>Unused permissions</h3>
          {advice.unused_permissions.length ? <ul>{advice.unused_permissions.map((item) => (
            <li key={`${item.source}>${item.destination}`}>
              <div><strong>{nameOf(item.source)} → {nameOf(item.destination)}</strong><small>Allowed, but not used in this window</small></div>
              <span className="cn-tag">Consider removing</span>
            </li>))}</ul> : <p className="ad-muted">Every allowed path was used.</p>}
        </section>
      </div>
    </Panel>
  );
}
