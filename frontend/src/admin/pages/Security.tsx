import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Download, Lock, ShieldCheck, ShieldOff } from "lucide-react";
import HoldButton from "@/components/kokonutui/hold-button";
import type { AdminIncident, AdminService, AdminSnapshot, LabStatus, PlatformService } from "../adminService";
import type { GraphFlow, GraphSelection } from "../graphMap";
// The graph library is large; load it only when the overview is opened.
const GraphMap = lazy(() => import("../graphMap").then((module) => ({ default: module.GraphMap })));
import { Drawer, Empty, PageHead, Panel, relative, Status, when } from "../ui";
import { errorText, useToaster } from "../toast";
import "../overview.css";

/*
 * Provider overview: service map, incidents, live connections and risk on one page.
 * Everything shown comes from API records (Hubble flows, detector windows, incidents, workloads);
 * motion plays only for traffic seen in the last 30 seconds.
 */

/* Plain-language names for services; anything unknown falls back to its technical name. */
const NAMES: Record<string, string> = {
  "shipfast-plugin": "ShipFast plugin", "northstar-web": "Northstar storefront", "northstar-api": "Northstar order system",
  "northstar-database": "Northstar database", "bloom-web": "Bloom storefront", "bloom-api": "Bloom order system",
  "bloom-database": "Bloom database", "order-ids": "Order ID service", payments: "Payments service", email: "Email service",
};
const ROLE_NAMES: Record<string, string> = { web: "storefront", api: "order system", database: "database", plugin: "plugin" };
/** Display name for any workload: known names first, then "<shop> <role>" from the slug (terra-pots-api → Terra Pots order system). */
export const nameOf = (value?: string | null) => {
  if (!value) return "Outside the cluster";
  if (NAMES[value]) return NAMES[value];
  const parts = value.split("-");
  const role = ROLE_NAMES[parts[parts.length - 1]];
  if (!role || parts.length < 2) return value;
  return `${parts.slice(0, -1).join(" ").replace(/\b\w/g, (c) => c.toUpperCase())} ${role}`;
};

const STATUS: Record<string, { value: string; label: string }> = {
  alert: { value: "alert", label: "Open" },
  quarantined: { value: "quarantined", label: "Isolated" },
  review: { value: "review", label: "Under review" },
  restored: { value: "restored", label: "Access restored" },
  closed: { value: "closed", label: "Closed" },
};
export const statusOf = (value: string) => STATUS[value] ?? { value, label: value };

const REASONS: Record<string, string> = {
  cross_tenant: "Tried to reach another shop",
  policy_denied: "Its connections were blocked by the security rules",
  horizontal_fanout: "Contacted many different services at once",
  vertical_port_fanout: "Tried many different ports on one service",
  volume_spike: "Sent a sudden burst of requests over a path that is normally quiet",
};

const TIMELINE: Record<string, string> = {
  "Graph anomaly detected": "Unusual activity detected",
  "Response: quarantined": "Isolated from the network",
  "Review started": "Review started",
  "Response: restored": "Access restored",
  "Alert dismissed": "Alert dismissed",
  "Closed by demo reset": "Closed when the demo was reset",
};

export const KIND: Record<PlatformService["kind"], string> = { shop: "Shop service", platform: "Shared platform service", plugin: "Installed plugin" };
export const WINDOW = 900;  // seconds of traffic shown
const RECENT = 30;   // traffic this fresh animates on the map

function level(risk: number) {
  if (risk >= 0.8) return "High";
  if (risk >= 0.5) return "Medium";
  return "Low";
}

/* One sentence describing what the service tried to do. */
export function summary(incident: AdminIncident) {
  const targets = new Set(incident.evidence.filter((e) => e.decision === "denied").map((e) => e.destinationName ?? "outside"));
  const blocked = incident.evidence.filter((e) => e.decision === "denied").length;
  if (!targets.size) return "Behaved unusually on connections it is allowed to use.";
  return `Tried to reach ${targets.size} service${targets.size === 1 ? "" : "s"} it is not allowed to use. ${blocked} attempt${blocked === 1 ? " was" : "s were"} blocked.`;
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now() / 1000), ms); return () => window.clearInterval(timer); }, [ms]);
  return now;
}

/** Eases the shown number toward the real value whenever it changes. */
function Count({ value }: { value: number }) {
  const [shown, setShown] = useState(value);
  const current = useRef(value);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { current.current = value; setShown(value); return; }
    const from = current.current, start = performance.now();
    let frame = 0;
    const step = (time: number) => {
      const p = Math.min(1, (time - start) / 600);
      current.current = from + (value - from) * (1 - (1 - p) ** 3);
      setShown(current.current);
      if (p < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <>{Math.round(shown).toLocaleString("en-IN")}</>;
}

export function ago(now: number, at?: number | null) {
  if (!at) return "never";
  const s = Math.max(0, Math.round(now - at));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)}m ago` : `${Math.floor(s / 3600)}h ago`;
}

export type IncidentAction = "quarantine" | "review" | "restore" | "dismiss";

export function useIncidentActions(service: AdminService, refresh: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const toaster = useToaster();
  function respond(incident: AdminIncident, action: IncidentAction) {
    setBusy(true);
    const name = nameOf(incident.sourceName);
    const verb = { quarantine: "Isolating", review: "Starting review of", restore: "Restoring access for", dismiss: "Dismissing alert for" }[action];
    const done = { quarantine: "is isolated", review: "is under review", restore: "has its access back", dismiss: "alert dismissed" }[action];
    return toaster.show(async () => {
      try { await service.respondToIncident(incident.id, action); await refresh(); }
      finally { setBusy(false); }
    }, {
      loading: `${verb} ${name}`,
      waiting: action === "review" || action === "dismiss" ? undefined : "Checking the change is in place",
      success: [`${name} ${done}`, "Added to the incident timeline"],
      error: (reason) => [`Could not update ${name}`, errorText(reason, "The change could not be confirmed")],
    });
  }
  return { busy, respond };
}

export function Security({ data, service, refresh, onViewAlerts }: { data: AdminSnapshot; service: AdminService; refresh: () => Promise<void>; onViewAlerts: () => void }) {
  const { incidents, traffic: rawTraffic, risk } = data.security;
  const [lab, setLab] = useState<LabStatus | null>(null);
  const [services, setServices] = useState<PlatformService[]>([]);
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [serviceName, setServiceName] = useState<string | null>(null);
  const { busy, respond: act } = useIncidentActions(service, refresh);
  const now = useNow();

  useEffect(() => {
    let active = true;
    const status = () => service.labStatus().then((value) => { if (active) setLab(value); }).catch(() => undefined);
    const fleet = () => service.platformServices().then((value) => { if (active) setServices(value); }).catch(() => undefined);
    void status(); void fleet();
    const statusTimer = window.setInterval(() => void status(), 5_000);
    const fleetTimer = window.setInterval(() => void fleet(), 10_000);
    return () => { active = false; window.clearInterval(statusTimer); window.clearInterval(fleetTimer); };
  }, [service]);

  const traffic = useMemo(() => rawTraffic.filter((item) => item.at >= now - WINDOW).sort((a, b) => a.at - b.at), [rawTraffic, now]);
  const blocked = traffic.filter((item) => item.decision === "denied");
  const isOpen = (item: AdminIncident) => !["restored", "closed"].includes(item.status);
  // Open incidents first, then newest, so the one that needs a decision is never buried.
  const sortedIncidents = useMemo(() => incidents.slice().sort((a, b) => Number(isOpen(b)) - Number(isOpen(a)) || b.createdAt - a.createdAt), [incidents]);
  const quarantined = useMemo(() => new Set(services.filter((item) => item.quarantined).map((item) => item.name)), [services]);

  // Graph built from the live workload list and observed flows: every tenant appears without code changes.
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [verdict, setVerdict] = useState<"all" | "allowed" | "denied">("all");
  const flows = useMemo(() => {
    const map = new Map<string, GraphFlow>();
    for (const item of traffic) {
      const destination = item.destinationName ?? "internet";
      const key = `${item.sourceName}>${destination}`;
      const flow = map.get(key) ?? { source: item.sourceName, destination, allowed: 0, blocked: 0, recent: false };
      if (item.decision === "denied") flow.blocked += 1; else flow.allowed += 1;
      flow.recent ||= now - item.at <= RECENT;
      map.set(key, flow);
    }
    return [...map.values()];
  }, [traffic, now]);
  const graphServices = useMemo(() => services.map((item) => ({ name: item.name, tenant: item.tenant, kind: item.kind, calls: item.calls, quarantined: item.quarantined })), [services]);
  const tableRows = traffic.slice().reverse().filter((item) => {
    if (verdict !== "all" && item.decision !== verdict) return false;
    if (selection?.node) return item.sourceName === selection.node || item.destinationName === selection.node;
    if (selection?.edge) return item.sourceName === selection.edge.source && (item.destinationName ?? "internet") === selection.edge.destination;
    return true;
  }).slice(0, 25);
  const liveSource = [...traffic].reverse().find((item) => item.decision === "denied" && now - item.at <= RECENT)?.sourceName;

  const incident = incidents.find((item) => item.id === incidentId) ?? null;
  const selectedService = services.find((item) => item.name === serviceName) ?? null;
  const telemetryFresh = Boolean(lab?.telemetry.fresh);

  async function respond(action: IncidentAction) {
    if (incident) await act(incident, action);
  }

  const alerts = sortedIncidents.filter((item) => item.status === "alert");
  const lockedIncidents = sortedIncidents.filter((item) => item.status === "quarantined" || item.status === "review");


  const banner = alerts.length
    ? { tone: "bad", icon: AlertTriangle, title: "The AI caught something.", text: `Suspect: ${nameOf(alerts[0].sourceName)}`,
        action: "See what happened", run: () => setIncidentId(alerts[0].id) }
    : lockedIncidents.length
      ? { tone: "warn", icon: Lock, title: `${nameOf(lockedIncidents[0].sourceName)} is locked out.`, text: "It can't reach anything.",
          action: "Review it", run: () => setIncidentId(lockedIncidents[0].id) }
      : lab?.protection === false
        ? { tone: "bad", icon: ShieldOff, title: "Protection is switched off.", text: "Tenant walls are down.", action: "", run: () => undefined }
        : { tone: "good", icon: ShieldCheck, title: "All quiet. Every shop is safe.", text: "No threats right now.", action: "", run: () => undefined };
  const BannerIcon = banner.icon;

  return (
    <>
      <PageHead title="Overview">
        <div className="ov-chips">
          <span className={`ov-chip ${telemetryFresh ? "good" : "warn"}`}><i aria-hidden="true" />{telemetryFresh ? "Live" : "Telemetry stale"}</span>
        </div>
      </PageHead>

      <section className={`ov-banner ${banner.tone}`}>
        <span className="ov-banner-icon"><BannerIcon size={26} aria-hidden="true" /></span>
        <div><h2>{banner.title}</h2><p>{banner.text}</p></div>
        {banner.action && <button className="ov-banner-go" onClick={banner.run}>{banner.action}<ArrowRight size={17} aria-hidden="true" /></button>}
      </section>


      <div className="ov-kpis">
        <Kpi label="Allowed" value={traffic.length - blocked.length} />
        <Kpi label="Blocked" value={blocked.length} tone={blocked.length ? "bad" : undefined} />
        <Kpi label="Alerts" value={alerts.length} tone={alerts.length ? "warn" : undefined} />
        <Kpi label="Locked out" value={quarantined.size} tone={quarantined.size ? "bad" : undefined} />
      </div>

      <div className="ov-main">
        <Panel title="Live service graph" subtitle={traffic.length ? "Click a service or a connection to filter the flows below." : "No traffic in the last 15 minutes."}
          action={selection?.node ? <button className="ad-link-button" onClick={() => setServiceName(selection.node ?? null)}>Details</button> : undefined}>
          <Suspense fallback={<div className="gm-canvas" />}><GraphMap services={graphServices} flows={flows} source={liveSource} selection={selection} onSelect={setSelection} /></Suspense>
        </Panel>
        <Panel title="Alerts" flush action={<button className="ad-link-button" onClick={onViewAlerts}>View all</button>}>
          {incidents.length
            ? <ul className="ad-incident-list">
                {sortedIncidents.map((item) => (
                  <li key={item.id}>
                    <button onClick={() => setIncidentId(item.id)}>
                      <span><strong>{nameOf(item.sourceName)}</strong><small>{relative(item.createdAt)}</small></span>
                      <Status {...statusOf(item.status)} />
                    </button>
                  </li>
                ))}
              </ul>
            : <div className="ov-pad"><Empty title="All clear" /></div>}
        </Panel>
      </div>

      <div className="ov-bottom">
        <Panel title="Flows" subtitle="Synced with the graph" flush>
          <div className="ov-flows-filter">
            <div className="ad-segment" role="group" aria-label="Verdict">
              {(["all", "allowed", "denied"] as const).map((value) => (
                <button key={value} className={verdict === value ? "active" : ""} aria-pressed={verdict === value} onClick={() => setVerdict(value)}>
                  {value === "all" ? "All" : value === "allowed" ? "Allowed" : "Blocked"}</button>))}
            </div>
            {selection && <span className="ov-chip">{selection.node ? nameOf(selection.node) : `${nameOf(selection.edge?.source)} → ${nameOf(selection.edge?.destination === "internet" ? null : selection.edge?.destination)}`}</span>}
            {selection && <button className="ov-clear" onClick={() => setSelection(null)}>Clear</button>}
          </div>
          {tableRows.length
            ? <ul className="ov-feed" aria-live="polite">
                {tableRows.map((item) => (
                  <li key={item.id} className={item.decision}>
                    <b>{item.decision === "denied" ? "Blocked" : item.decision === "allowed" ? "Allowed" : "Unknown"}</b>
                    <p><span><strong>{nameOf(item.sourceName)}</strong> → <strong>{nameOf(item.destinationName)}</strong></span></p>
                    <time>{ago(now, item.at)}</time>
                  </li>
                ))}
              </ul>
            : <div className="ov-pad"><Empty title="Nothing yet" /></div>}
        </Panel>
        <Panel title="AI risk">
          <RiskBars risk={risk} />
        </Panel>
      </div>

      <Drawer open={Boolean(incident)} title={incident ? nameOf(incident.sourceName) : ""}
        subtitle={incident ? `${statusOf(incident.status).label} incident · ${summary(incident)}` : ""} onClose={() => setIncidentId(null)}>
        {incident && <IncidentDetail incident={incident} busy={busy} respond={respond} onEvidence={() => void downloadEvidence(service, incident.id)} />}
      </Drawer>
      <Drawer open={Boolean(serviceName)} title={nameOf(serviceName)}
        subtitle={selectedService ? `${selectedService.tenant} · ${KIND[selectedService.kind]}` : "Service"} onClose={() => setServiceName(null)}>
        {serviceName && <ServiceDetail name={serviceName} item={selectedService} traffic={traffic} now={now} />}
      </Drawer>
    </>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number; tone?: "bad" | "warn" }) {
  return (
    <div className={`ov-kpi ${tone ?? ""}`}>
      <span>{label}</span>
      <strong className="ad-num"><Count value={value} /></strong>
    </div>
  );
}

export function RiskBars({ risk }: { risk: AdminSnapshot["security"]["risk"] }) {
  const rows = useMemo(() => {
    const by = new Map<string, { peak: number; threshold: number; corroborated: boolean }>();
    for (const item of risk) {
      const entry = by.get(item.sourceName) ?? { peak: 0, threshold: item.threshold, corroborated: false };
      entry.peak = Math.max(entry.peak, item.accumulatedRisk);
      entry.threshold = item.threshold;
      entry.corroborated ||= item.corroborated;
      by.set(item.sourceName, entry);
    }
    return [...by.entries()].sort((a, b) => b[1].peak - a[1].peak).slice(0, 6);
  }, [risk]);
  if (!rows.length) return <Empty title="Nothing scored yet" />;
  return (
    <ul className="ov-risk">
      {rows.map(([name, entry]) => {
        const over = entry.peak >= entry.threshold;
        return (
          <li key={name} className={over ? "over" : ""}>
            <div><span>{nameOf(name)}</span><strong className="ad-num">{Math.round(entry.peak * 100)}%</strong></div>
            <i><b style={{ width: `${entry.peak * 100}%` }} /><em style={{ left: `${entry.threshold * 100}%` }} title={`Alert level ${Math.round(entry.threshold * 100)}%`} /></i>
                      </li>
        );
      })}
    </ul>
  );
}

type Traffic = AdminSnapshot["security"]["traffic"];
type PeerRows = Array<[string, { allowed: number; blocked: number; last: number }]>;

function groupByPeer(events: Traffic, key: "sourceName" | "destinationName"): PeerRows {
  const map = new Map<string, { allowed: number; blocked: number; last: number }>();
  for (const event of events) {
    const peer = event[key] ?? "";
    const entry = map.get(peer) ?? { allowed: 0, blocked: 0, last: 0 };
    if (event.decision === "denied") entry.blocked += 1; else entry.allowed += 1;
    entry.last = Math.max(entry.last, event.at);
    map.set(peer, entry);
  }
  return [...map.entries()].sort((a, b) => b[1].blocked - a[1].blocked || b[1].last - a[1].last);
}

function PeerList({ rows, now }: { rows: PeerRows; now: number }) {
  if (!rows.length) return <p className="ov-none">None in the last 15 minutes.</p>;
  return (
    <ul className="ad-evidence">
      {rows.map(([peer, entry]) => (
        <li key={peer}>
          <span>{nameOf(peer || null)}</span>
          <Status value={entry.blocked ? "denied" : "allowed"}
            label={`${entry.blocked ? (entry.allowed ? "Blocked and allowed" : "Blocked") : "Allowed"} · ${ago(now, entry.last)}`} />
        </li>
      ))}
    </ul>
  );
}

export function ServiceDetail({ name, item, traffic, now }: { name: string; item: PlatformService | null; traffic: Traffic; now: number }) {
  return (
    <div className="ov-service">
      {item
        ? <>
            <div className="ov-service-head">
              <Status value={item.quarantined ? "quarantined" : item.status === "running" ? "online" : "unavailable"}
                label={item.quarantined ? "Quarantined" : item.status === "running" ? "Running" : item.status} />
              {item.quarantined && <p><Lock size={14} aria-hidden="true" /> Cut off from every other service. The pod keeps running so it can be investigated.</p>}
            </div>
            <h3>Allowed to call</h3>
            {item.calls.length
              ? <div className="ov-tags">{item.calls.map((call) => <span key={call}>{nameOf(call)}</span>)}</div>
              : <p className="ov-none">Nothing. It only receives calls.</p>}
          </>
        : <p className="ov-none">Not a SecureCloud-managed workload.</p>}
      <h3>Its outgoing connections</h3>
      <PeerList rows={groupByPeer(traffic.filter((event) => event.sourceName === name), "destinationName")} now={now} />
      <h3>Who connected to it</h3>
      <PeerList rows={groupByPeer(traffic.filter((event) => event.destinationName === name), "sourceName")} now={now} />
      <p className="ov-none">Anything not on the allow-list is dropped by a default-deny Cilium policy.</p>
    </div>
  );
}

/** Save an incident's evidence pack (flows, model findings, containment, audit, live policies, SHA-256). */
export async function downloadEvidence(service: AdminService, incidentId: string) {
  const blob = await service.evidence(incidentId);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `evidence-${incidentId}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

export function IncidentDetail({ incident, busy, respond, onEvidence }: { incident: AdminIncident; busy: boolean; respond: (action: "quarantine" | "review" | "restore" | "dismiss") => Promise<void>; onEvidence?: () => void }) {
  const finding = incident.finding;
  const reasons = finding ? Object.entries(finding.supporting_facts).filter(([, value]) => value).map(([key]) => REASONS[key] ?? key.replaceAll("_", " ")) : [];
  const risk = finding?.accumulated_risk ?? 0;
  const recommended = finding?.response === "containment-recommended";

  // Group attempts by destination: "Bloom order system · blocked 4 times".
  const targets = useMemo(() => {
    const map = new Map<string, { name: string; blocked: number; allowed: number }>();
    for (const event of incident.evidence) {
      const key = event.destinationName ?? "outside";
      const entry = map.get(key) ?? { name: nameOf(event.destinationName), blocked: 0, allowed: 0 };
      if (event.decision === "denied") entry.blocked += 1; else entry.allowed += 1;
      map.set(key, entry);
    }
    return [...map.values()].sort((a, b) => b.blocked - a.blocked);
  }, [incident.evidence]);

  // Timeline: plain titles; repeated "another blocked attempt" steps collapse into one line.
  const timeline = useMemo(() => {
    const steps: { at: number; title: string }[] = [];
    let extra = 0;
    for (const step of incident.trace) {
      if (step.title === "Additional anomalous edge") { extra += 1; continue; }
      if (extra) { steps.push({ at: step.at, title: `${extra} more suspicious connection${extra === 1 ? "" : "s"} added to the evidence` }); extra = 0; }
      steps.push({ at: step.at, title: TIMELINE[step.title] ?? step.title });
    }
    if (extra) steps.push({ at: incident.trace.at(-1)?.at ?? incident.createdAt, title: `${extra} more suspicious connection${extra === 1 ? "" : "s"} added to the evidence` });
    return steps;
  }, [incident.trace, incident.createdAt]);

  return (
    <section className="ad-panel ad-incident">
      <header>
        <div><p className="ad-kicker">Incident</p><h2>{nameOf(incident.sourceName)}</h2><p>{summary(incident)}</p></div>
        <Status {...statusOf(incident.status)} />
      </header>
      <div className="ad-panel-body">
        {finding && (
          <div className="ad-risk">
            <h3>Why it was flagged</h3>
            <div className="ad-risk-grid">
              <RiskValue label="Risk level" value={risk} threshold={finding.threshold} text={`${level(risk)} · ${Math.round(risk * 100)}%`} />
            </div>
            <ul className="ad-reasons">
              <li>Its behaviour looked very different from normal (the AI model scored it {Math.round(risk * 100)}%).</li>
              {reasons.map((reason) => <li key={reason}>{reason}</li>)}
            </ul>
          </div>
        )}
        <div>
          <h3>What it tried to reach</h3>
          <ul className="ad-evidence">{targets.map((target) => (
            <li key={target.name}>
              <span>{target.name}</span>
              <Status value={target.blocked ? "denied" : "allowed"}
                label={target.blocked ? `Blocked ${target.blocked} time${target.blocked === 1 ? "" : "s"}` : `Allowed ${target.allowed} time${target.allowed === 1 ? "" : "s"}`} />
            </li>
          ))}</ul>
        </div>
        <div>
          <h3>Timeline</h3>
          <ol className="ad-trace">{timeline.map((step, index) => (
            <li key={`${step.at}-${index}`}><span aria-hidden="true" /><p><strong>{step.title}</strong></p><time>{when(step.at)}</time></li>
          ))}</ol>
        </div>
        <details className="ad-tech">
          <summary>Technical details</summary>
          <dl className="ad-facts ad-facts-grid">
            <div><dt>Workload</dt><dd><code>{incident.sourceName}</code></dd></div>
            <div><dt>Opened</dt><dd>{when(incident.createdAt)}</dd></div>
            {finding && <div><dt>Model</dt><dd>{finding.model_version}</dd></div>}
            {finding && <div><dt>Scores</dt><dd>anomaly {finding.anomaly_score.toFixed(3)} · risk {finding.accumulated_risk.toFixed(3)} · baseline {finding.baseline_score.toFixed(3)} · threshold {finding.threshold.toFixed(2)}</dd></div>}
          </dl>
          <ul className="ad-evidence">{incident.evidence.slice(0, 20).map((event) => (
            <li key={event.id}><code>{event.sourceName} → {event.destinationName ?? "world"}:{event.port}</code><small>{event.reason}</small></li>
          ))}</ul>
        </details>
      </div>
      <footer>
        {incident.status === "alert" && (
          <HoldButton variant="red" holdDuration={1200} disabled={busy || !recommended}
            holdingLabel="Keep holding to isolate" completeLabel="Isolation requested" resetAfter={0}
            aria-label="Isolate this service" onHoldComplete={() => void respond("quarantine")}>
            Isolate this service
          </HoldButton>
        )}
        {incident.status === "alert" && <button className="ad-button" disabled={busy} onClick={() => void respond("dismiss")}>Dismiss</button>}
        {incident.status === "quarantined" && <button className="ad-button" disabled={busy} onClick={() => void respond("review")}>Start review</button>}
        {incident.status === "review" && <button className="ad-button ad-button-primary" disabled={busy} onClick={() => void respond("restore")}>Restore access</button>}
        {onEvidence && <button className="ad-button" onClick={onEvidence}><Download size={15} />Evidence pack</button>}
        <small>
          {incident.status === "alert"
            ? recommended ? "Recommended: isolate it. The AI flagged it and its blocked attempts confirm it." : "Not enough evidence to recommend isolating it. Review and decide."
            : incident.status === "quarantined" ? "Cut off from every other service. The pod keeps running so it can be investigated."
            : incident.status === "review" ? "Still isolated while you review. Restore access when it is safe."
            : "No action needed."}
        </small>
      </footer>
    </section>
  );
}

function RiskValue({ label, value, threshold, text }: { label: string; value: number; threshold?: number; text: string }) {
  const over = threshold !== undefined && value >= threshold;
  return (
    <div className={over ? "over" : ""}>
      <span>{label}</span>
      <strong>{text}</strong>
      <i><b style={{ width: `${Math.min(100, value * 100)}%` }} /></i>
    </div>
  );
}
