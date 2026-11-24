import { useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import HoldButton from "@/components/kokonutui/hold-button";
import type { AdminIncident, AdminService, AdminSnapshot } from "../adminService";
import { AreaChart } from "../charts";
import { Empty, PageHead, Panel, relative, Status, when } from "../ui";
import { errorText, useToaster } from "../toast";

export function Security({ data, service, refresh }: { data: AdminSnapshot; service: AdminService; refresh: () => Promise<void> }) {
  const incidents = data.security.incidents;
  const [selectedId, setSelectedId] = useState(incidents.find((item) => !["restored", "closed"].includes(item.status))?.id ?? incidents[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const toaster = useToaster();
  const incident = incidents.find((item) => item.id === selectedId) ?? incidents[0];
  const exact = data.security.applicationEvents.filter((event) => event.correlation?.status === "exact").length;
  const denied = data.security.traffic.filter((item) => item.decision === "denied");
  const open = incidents.filter((item) => !["restored", "closed"].includes(item.status)).length;

  const riskSeries = useMemo(() => {
    const source = incident?.sourceName;
    const observations = data.security.risk
      .filter((item) => !source || item.sourceName === source)
      .slice()
      .sort((a, b) => a.windowEnd - b.windowEnd)
      .slice(-40);
    return observations;
  }, [data.security.risk, incident?.sourceName]);
  const threshold = riskSeries[riskSeries.length - 1]?.threshold;

  async function respond(action: "quarantine" | "review" | "restore" | "dismiss") {
    if (!incident) return;
    setBusy(true);
    const verb = { quarantine: "Quarantining", review: "Starting review of", restore: "Restoring", dismiss: "Dismissing alert for" }[action];
    const done = { quarantine: "quarantined and verified", review: "under review", restore: "restored and verified", dismiss: "alert dismissed" }[action];
    toaster.show(async () => {
      try { await service.respondToIncident(incident.id, action); await refresh(); }
      finally { setBusy(false); }
    }, {
      loading: `${verb} ${incident.sourceName}`,
      waiting: action === "review" || action === "dismiss" ? undefined : "Waiting for Cilium policy read-back",
      success: [`${incident.sourceName} ${done}`, "Recorded in the incident trace"],
      error: (reason) => [`Could not ${action} ${incident.sourceName}`, errorText(reason, "The response was not verified")],
    });
  }

  return (
    <>
      <PageHead title="Security activity" description="Workload traffic, temporal-graph risk, policy facts and verified incident response from SecureCloud.">
        <button className="ad-button" onClick={() => void refresh()}><RefreshCw size={15} />Refresh</button>
      </PageHead>
      <div className="ad-kpis ad-kpis-compact">
        <div className={`ad-kpi ${open ? "ad-kpi-alert" : ""}`}><span className="ad-kpi-label">Open incidents</span><strong className="ad-kpi-value">{open}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Blocked connections</span><strong className="ad-kpi-value">{denied.length}</strong></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Request-to-flow links</span><strong className="ad-kpi-value">{exact}</strong><small className="ad-kpi-note">exact Hubble matches</small></div>
        <div className="ad-kpi"><span className="ad-kpi-label">Risk windows scored</span><strong className="ad-kpi-value">{data.security.risk.length}</strong></div>
      </div>

      {!incident
        ? <Panel><Empty title="No security incidents">
            <ShieldCheck size={18} aria-hidden="true" /> SecureCloud has not flagged any workload for this store. Policy decisions and risk scores appear here as Hubble records traffic.
          </Empty></Panel>
        : <div className="ad-security">
            <Panel title="Incidents" flush>
              <ul className="ad-incident-list">
                {incidents.map((item) => (
                  <li key={item.id}>
                    <button className={item.id === incident.id ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                      <span><strong>{item.sourceName}</strong><small>{item.reason}</small><small>{relative(item.createdAt)}</small></span>
                      <Status value={item.status} />
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
            <IncidentDetail incident={incident} busy={busy} respond={respond} />
          </div>}

      {riskSeries.length > 1 && (
        <Panel title="Accumulated risk" subtitle={`${incident?.sourceName ?? "All workloads"} · temporal-graph model, per scoring window`}>
          <AreaChart ariaLabel="Accumulated risk per scoring window" format={(value) => value.toFixed(2)} fixedMax={1} height={220}
            threshold={threshold !== undefined ? { value: threshold, label: `threshold ${threshold.toFixed(2)}` } : undefined}
            points={riskSeries.map((item) => ({
              label: new Date(item.windowEnd * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }),
              value: item.accumulatedRisk,
              detail: `${item.sourceName} → ${item.destinationName} · GNN ${item.anomalyScore.toFixed(2)}`,
            }))} />
        </Panel>
      )}

      <div className="ad-grid-main">
        <Panel title="Recent network decisions" subtitle="Observed by Cilium/Hubble between workloads" flush>
          {data.security.traffic.length
            ? <div className="ad-table-wrap"><table className="ad-table">
                <thead><tr><th>Connection</th><th>Reason</th><th>Verdict</th><th>When</th></tr></thead>
                <tbody>{data.security.traffic.slice(0, 12).map((event) => (
                  <tr key={event.id}>
                    <td><code>{event.sourceName} → {event.destinationName}:{event.port}</code></td>
                    <td>{event.reason.replaceAll("-", " ")}</td>
                    <td><Status value={event.decision} /></td>
                    <td>{relative(event.at)}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            : <Empty title="No network decisions recorded">Flows appear when the Hubble collector is running.</Empty>}
        </Panel>
        <Panel title="Correlated application requests" subtitle="Retail API requests matched to network flows" flush>
          <ApplicationEvidence items={data.security.applicationEvents} />
        </Panel>
      </div>
    </>
  );
}

function IncidentDetail({ incident, busy, respond }: { incident: AdminIncident; busy: boolean; respond: (action: "quarantine" | "review" | "restore" | "dismiss") => Promise<void> }) {
  const facts = incident.finding ? Object.entries(incident.finding.supporting_facts).filter(([, value]) => value).map(([key]) => key.replaceAll("_", " ")) : [];
  return (
    <section className="ad-panel ad-incident">
      <header>
        <div><p className="ad-kicker">Incident evidence</p><h2>{incident.sourceName}</h2><p>{incident.reason}</p></div>
        <Status value={incident.status} />
      </header>
      <div className="ad-panel-body">
        <dl className="ad-facts ad-facts-grid">
          <div><dt>Source workload</dt><dd>{incident.sourceName}</dd></div>
          <div><dt>Created</dt><dd>{when(incident.createdAt)}</dd></div>
          <div><dt>Application requests</dt><dd>{incident.applicationEvents.length || "None linked"}</dd></div>
          <div><dt>Response state</dt><dd>{incident.containment?.status ?? incident.status}</dd></div>
        </dl>
        {incident.finding
          ? <div className="ad-risk">
              <h3>Temporal risk evidence</h3>
              <div className="ad-risk-grid">
                <RiskValue label="GNN anomaly" value={incident.finding.anomaly_score} threshold={incident.finding.threshold} />
                <RiskValue label="Accumulated risk" value={incident.finding.accumulated_risk} threshold={incident.finding.threshold} />
                <RiskValue label="Frequency baseline" value={incident.finding.baseline_score} />
                <RiskValue label="Threshold" value={incident.finding.threshold} />
              </div>
              <p><strong>Model:</strong> {incident.finding.model_version}</p>
              <p><strong>Independent facts:</strong> {facts.length ? facts.join(", ") : "None recorded, observation only"}</p>
            </div>
          : <p className="ad-info">This incident has deterministic policy evidence but no persisted temporal-model finding.</p>}
        <div>
          <h3>Network evidence</h3>
          <ul className="ad-evidence">{incident.evidence.map((event) => (
            <li key={event.id}><code>{event.sourceName} → {event.destinationName}:{event.port}</code><Status value={event.decision} /></li>
          ))}</ul>
        </div>
        <div>
          <h3>Response trace</h3>
          <ol className="ad-trace">{incident.trace.map((step) => (
            <li key={`${step.at}-${step.title}`}><span aria-hidden="true" /><p><strong>{step.title}</strong><small>{step.detail}</small></p><time>{when(step.at)}</time></li>
          ))}</ol>
        </div>
      </div>
      <footer>
        {incident.status === "alert" && (
          <HoldButton variant="red" holdDuration={1200} disabled={busy || incident.finding?.response !== "containment-recommended"}
            holdingLabel="Keep holding to quarantine" completeLabel="Quarantine requested" resetAfter={0}
            aria-label="Quarantine workload" onHoldComplete={() => void respond("quarantine")}>
            Quarantine workload
          </HoldButton>
        )}
        {incident.status === "alert" && <button className="ad-button" disabled={busy} onClick={() => void respond("dismiss")}>Dismiss alert</button>}
        {incident.status === "quarantined" && <button className="ad-button" disabled={busy} onClick={() => void respond("review")}>Start review</button>}
        {incident.status === "review" && <button className="ad-button ad-button-primary" disabled={busy} onClick={() => void respond("restore")}>Restore previous policy</button>}
        <small>{incident.finding?.response === "containment-recommended" ? "Response is supported by model risk and independent facts." : "No automatic response recommendation. Review the evidence."}</small>
      </footer>
    </section>
  );
}

function RiskValue({ label, value, threshold }: { label: string; value: number; threshold?: number }) {
  const over = threshold !== undefined && value >= threshold;
  return (
    <div className={over ? "over" : ""}>
      <span>{label}</span>
      <strong>{value.toFixed(3)}</strong>
      <i><b style={{ width: `${Math.min(100, value * 100)}%` }} /></i>
    </div>
  );
}

function ApplicationEvidence({ items }: { items: AdminSnapshot["security"]["applicationEvents"] }) {
  if (!items.length) return <Empty title="No correlated requests yet">Security-relevant retail API requests appear here once matched to flows.</Empty>;
  return (
    <div className="ad-table-wrap"><table className="ad-table">
      <thead><tr><th>Request</th><th>Connection</th><th>Result</th><th>Flow match</th></tr></thead>
      <tbody>{items.slice(0, 12).map((item) => (
        <tr key={item.id}>
          <td><strong>{item.action.replaceAll(".", " ")}</strong><small>{item.request_id.slice(0, 8)}</small></td>
          <td><code>{item.source_workload} → {item.destination_workload}:{item.destination_port ?? "-"}</code></td>
          <td><Status value={item.result} /></td>
          <td><Status value={item.correlation?.status ?? "unmatched"} /><small>{item.correlation?.reason ?? "No resolved flow link"}</small></td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}
