import { useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import HoldButton from "@/components/kokonutui/hold-button";
import type { AdminIncident, AdminService, AdminSnapshot } from "../adminService";
import { AreaChart } from "../charts";
import { Empty, PageHead, Panel, relative, Status, when } from "../ui";
import { errorText, useToaster } from "../toast";

/* Plain-language names for services; anything unknown falls back to its technical name. */
const NAMES: Record<string, string> = {
  "shipfast-plugin": "ShipFast plugin", "northstar-web": "Northstar storefront", "northstar-api": "Northstar order system",
  "northstar-database": "Northstar database", "bloom-web": "Bloom storefront", "bloom-api": "Bloom order system",
  "bloom-database": "Bloom database", "order-ids": "Order ID service", payments: "Payments service", email: "Email service",
};
const nameOf = (value?: string | null) => (value ? NAMES[value] ?? value : "Outside the cluster");

const STATUS: Record<string, { value: string; label: string }> = {
  alert: { value: "alert", label: "Open" },
  quarantined: { value: "quarantined", label: "Isolated" },
  review: { value: "review", label: "Under review" },
  restored: { value: "restored", label: "Access restored" },
  closed: { value: "closed", label: "Closed" },
};
const statusOf = (value: string) => STATUS[value] ?? { value, label: value };

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

function level(risk: number) {
  if (risk >= 0.8) return "High";
  if (risk >= 0.5) return "Medium";
  return "Low";
}

/* One sentence describing what the service tried to do. */
function summary(incident: AdminIncident) {
  const targets = new Set(incident.evidence.filter((e) => e.decision === "denied").map((e) => e.destinationName ?? "outside"));
  const blocked = incident.evidence.filter((e) => e.decision === "denied").length;
  if (!targets.size) return "Behaved unusually on connections it is allowed to use.";
  return `Tried to reach ${targets.size} service${targets.size === 1 ? "" : "s"} it is not allowed to use. ${blocked} attempt${blocked === 1 ? " was" : "s were"} blocked.`;
}

export function Security({ data, service, refresh }: { data: AdminSnapshot; service: AdminService; refresh: () => Promise<void> }) {
  const incidents = data.security.incidents;
  const [selectedId, setSelectedId] = useState(incidents.find((item) => !["restored", "closed"].includes(item.status))?.id ?? incidents[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const toaster = useToaster();
  const incident = incidents.find((item) => item.id === selectedId) ?? incidents[0];
  const blocked = data.security.traffic.filter((item) => item.decision === "denied");
  const open = incidents.filter((item) => !["restored", "closed"].includes(item.status)).length;
  const isolated = incidents.filter((item) => item.status === "quarantined" || item.status === "review").length;

  const riskSeries = useMemo(() => {
    const source = incident?.sourceName;
    return data.security.risk
      .filter((item) => !source || item.sourceName === source)
      .slice()
      .sort((a, b) => a.windowEnd - b.windowEnd)
      .slice(-40);
  }, [data.security.risk, incident?.sourceName]);
  const threshold = riskSeries[riskSeries.length - 1]?.threshold;

  async function respond(action: "quarantine" | "review" | "restore" | "dismiss") {
    if (!incident) return;
    setBusy(true);
    const name = nameOf(incident.sourceName);
    const verb = { quarantine: "Isolating", review: "Starting review of", restore: "Restoring access for", dismiss: "Dismissing alert for" }[action];
    const done = { quarantine: "is isolated", review: "is under review", restore: "has its access back", dismiss: "alert dismissed" }[action];
    toaster.show(async () => {
      try { await service.respondToIncident(incident.id, action); await refresh(); }
      finally { setBusy(false); }
    }, {
      loading: `${verb} ${name}`,
      waiting: action === "review" || action === "dismiss" ? undefined : "Checking the change is in place",
      success: [`${name} ${done}`, "Added to the incident timeline"],
      error: (reason) => [`Could not update ${name}`, errorText(reason, "The change could not be confirmed")],
    });
  }

  return (
    <>
      <PageHead title="Security activity" description="What SecureCloud blocked, what looks suspicious, and what was done about it.">
        <button className="ad-button" onClick={() => void refresh()}><RefreshCw size={15} />Refresh</button>
      </PageHead>
      <div className="ad-kpis ad-kpis-compact">
        <div className={`ad-kpi ${open ? "ad-kpi-alert" : ""}`}><span className="ad-kpi-label">Open incidents</span><strong className="ad-kpi-value">{open}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Blocked attempts</span><strong className="ad-kpi-value">{blocked.length}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Services isolated</span><strong className="ad-kpi-value">{isolated}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Shops protected</span><strong className="ad-kpi-value">2</strong><small className="ad-kpi-note">Northstar and Bloom</small></div>
      </div>

      {!incident
        ? <Panel><Empty title="All clear">
            <ShieldCheck size={18} aria-hidden="true" /> Nothing suspicious so far. Incidents appear here when SecureCloud spots a service behaving unusually.
          </Empty></Panel>
        : <div className="ad-security">
            <Panel title="Incidents" flush>
              <ul className="ad-incident-list">
                {incidents.map((item) => (
                  <li key={item.id}>
                    <button className={item.id === incident.id ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                      <span><strong>{nameOf(item.sourceName)}</strong><small>{summary(item)}</small><small>{relative(item.createdAt)}</small></span>
                      <Status {...statusOf(item.status)} />
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <IncidentDetail incident={incident} busy={busy} respond={respond} />
          </div>}

      {riskSeries.length > 1 && (
        <Panel title="Risk over time" subtitle={`How unusual ${nameOf(incident?.sourceName)}'s behaviour looks, from 0% (normal) to 100%`}>
          <AreaChart ariaLabel="Risk over time" format={(value) => `${Math.round(value * 100)}%`} fixedMax={1} height={200}
            threshold={threshold !== undefined ? { value: threshold, label: `alert level ${Math.round(threshold * 100)}%` } : undefined}
            points={riskSeries.map((item) => ({
              label: new Date(item.windowEnd * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
              value: item.accumulatedRisk,
              detail: `${nameOf(item.sourceName)} → ${nameOf(item.destinationName)}`,
            }))} />
        </Panel>
      )}

      <Panel title="Recent connections" subtitle="Who tried to talk to whom, and whether it was allowed" flush>
        {data.security.traffic.length
          ? <div className="ad-table-wrap"><table className="ad-table">
              <thead><tr><th>From</th><th>To</th><th>Result</th><th>When</th></tr></thead>
              <tbody>{data.security.traffic.slice(-12).reverse().map((event) => (
                <tr key={event.id}>
                  <td>{nameOf(event.sourceName)}</td>
                  <td>{nameOf(event.destinationName)}</td>
                  <td><Status value={event.decision} label={event.decision === "denied" ? "Blocked" : "Allowed"} /></td>
                  <td>{relative(event.at)}</td>
                </tr>
              ))}</tbody>
            </table></div>
          : <Empty title="No connections recorded yet">They appear here as soon as traffic is seen.</Empty>}
      </Panel>
    </>
  );
}

function IncidentDetail({ incident, busy, respond }: { incident: AdminIncident; busy: boolean; respond: (action: "quarantine" | "review" | "restore" | "dismiss") => Promise<void> }) {
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
