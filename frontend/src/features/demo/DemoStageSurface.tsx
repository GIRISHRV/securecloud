import { useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { ActionButton } from "../../components/ActionButton";
import { Icon } from "../../components/Icon";
import { Badge, Empty, time } from "../../components/ui";
import type { Incident } from "../../domain/models";
import { formatRiskScore, selectRiskEvidence } from "../../domain/riskEvidence";
import { TrafficTable } from "../network/TrafficTable";

const incidentTone = (status: Incident["status"]) =>
  status === "restored"
    ? "green"
    : status === "quarantined"
      ? "red"
      : status === "review"
        ? "blue"
        : "amber";

function IncidentStages({ status }: { status: Incident["status"] }) {
  const stages = ["alert", "quarantined", "review", "restored"] as const;
  return (
    <div className="response-stages demo-response-stages">
      {stages.map((stage, index) => (
        <span
          key={stage}
          className={stages.indexOf(status) >= index ? "reached" : ""}
        >
          <b>{index + 1}</b>
          {stage}
        </span>
      ))}
    </div>
  );
}

function Applications() {
  const { data } = usePortal();
  const [selected, setSelected] = useState<"retail" | "vendor">("retail");
  const retail = data.workloads.find(
    (workload) => workload.name === "frontend" && workload.previewUrl,
  );
  const vendor = data.workloads.find(
    (workload) => workload.name === "vendor-web" && workload.previewUrl,
  );
  const workload = selected === "retail" ? retail : vendor;
  return (
    <div className="demo-app-stage">
      <div className="demo-inline-tabs" aria-label="Demo applications">
        <button
          aria-pressed={selected === "retail"}
          onClick={() => setSelected("retail")}
        >
          RetailCo storefront
        </button>
        <button
          aria-pressed={selected === "vendor"}
          onClick={() => setSelected("vendor")}
        >
          FacilitiesVendor portal
        </button>
        {workload?.previewUrl ? (
          <a href={workload.previewUrl} target="_blank" rel="noreferrer">
            Open full screen <Icon name="arrow" size={14} />
          </a>
        ) : null}
      </div>
      {workload?.previewUrl ? (
        <iframe
          className="demo-app-frame"
          src={workload.previewUrl}
          title={
            selected === "retail"
              ? "RetailCo application"
              : "FacilitiesVendor application"
          }
        />
      ) : (
        <div className="demo-stage-empty">
          <Empty title="Application unavailable">
            Start the local application port forwards before presenting.
          </Empty>
        </div>
      )}
    </div>
  );
}

function RiskEvidence() {
  const { data } = usePortal();
  const observations = selectRiskEvidence(data.security?.observations ?? []);
  if (!observations.length) {
    return (
      <div className="demo-stage-empty">
        <Empty title="No risk observations">
          Generate resolved traffic to populate the model comparison.
        </Empty>
      </div>
    );
  }
  return (
    <div className="risk-table-wrap demo-risk-stage">
      <table className="risk-table" aria-label="Demo temporal risk evidence">
        <thead>
          <tr>
            <th>Connection</th>
            <th>GNN</th>
            <th>Accumulated / threshold</th>
            <th>Baseline</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {observations.map((item) => (
            <tr
              key={`${item.windowStart}-${item.sourceId}-${item.destinationId}`}
            >
              <td>
                <strong>{item.sourceName}</strong>
                <span> → {item.destinationName}</span>
              </td>
              <td>{formatRiskScore(item.anomalyScore)}</td>
              <td>
                {formatRiskScore(item.accumulatedRisk)} / {formatRiskScore(item.threshold)}
              </td>
              <td>{formatRiskScore(item.baselineScore)}</td>
              <td>
                <Badge
                  tone={
                    item.response === "containment-recommended"
                      ? "red"
                      : "neutral"
                  }
                >
                  {item.response === "containment-recommended"
                    ? "Respond"
                    : "Observe"}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Response() {
  const { data, service } = usePortal();
  const { error, busy, run } = useAction();
  const incident =
    data.incidents.find((item) => item.status !== "restored") ??
    data.incidents[0];
  if (!incident) {
    return (
      <div className="demo-stage-empty">
        <Empty title="No incident available">
          Capture a corroborated temporal finding before presenting response.
        </Empty>
      </div>
    );
  }
  return (
    <div className="demo-response-stage">
      <div className="demo-incident-heading">
        <div>
          <small>INC-{incident.id.slice(0, 6).toUpperCase()}</small>
          <h3>{incident.sourceName}</h3>
          <p>{incident.reason}</p>
        </div>
        <Badge tone={incidentTone(incident.status)}>{incident.status}</Badge>
      </div>
      <IncidentStages status={incident.status} />
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="demo-response-actions">
        {incident.status === "alert" ? (
          <ActionButton
            className="button danger"
            disabled={busy}
            onClick={() => void run(() => service.quarantine(incident.id))}
          >
            <Icon name="shield" size={15} /> Quarantine workload
          </ActionButton>
        ) : null}
        {incident.status === "quarantined" ? (
          <ActionButton
            className="button primary"
            disabled={busy}
            onClick={() => void run(() => service.review(incident.id))}
          >
            Start review <Icon name="arrow" size={15} />
          </ActionButton>
        ) : null}
        {incident.status === "review" ? (
          <ActionButton
            className="button primary"
            disabled={busy}
            onClick={() => void run(() => service.restore(incident.id))}
          >
            <Icon name="refresh" size={15} /> Restore workload
          </ActionButton>
        ) : null}
        {incident.status === "restored" ? (
          <Badge tone="green">Recovery complete</Badge>
        ) : null}
      </div>
      <div className="demo-contained-evidence">
        <h3>Triggering evidence</h3>
        <TrafficTable events={incident.evidence} />
      </div>
    </div>
  );
}

function Recovery() {
  const { data } = usePortal();
  const incident = data.incidents.find((item) => item.status === "restored");
  if (!incident) {
    return (
      <div className="demo-stage-empty">
        <Empty title="No restored incident">
          Complete quarantine, review, and restore to populate this stage.
        </Empty>
      </div>
    );
  }
  return (
    <div className="demo-recovery-stage">
      <div className="demo-recovery-heading">
        <div>
          <small>Recovered workload</small>
          <h3>{incident.sourceName}</h3>
        </div>
        <Badge tone="green">Restored</Badge>
      </div>
      <IncidentStages status="restored" />
      <ol className="demo-trace">
        {incident.trace.map((entry, index) => (
          <li key={`${entry.at}-${index}`}>
            <span>
              <Icon
                name={
                  index === 0
                    ? "activity"
                    : index === incident.trace.length - 1
                      ? "check"
                      : "shield"
                }
                size={14}
              />
            </span>
            <div>
              <strong>{entry.title}</strong>
              <small>{time(entry.at)}</small>
              <p>{entry.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function DemoStageSurface({ selected }: { selected: number }) {
  const { data } = usePortal();
  if (selected === 0) return <Applications />;
  if (selected === 1)
    return (
      <TrafficTable
        events={data.traffic
          .filter((event) => event.decision === "allowed")
          .slice(-12)
          .reverse()}
      />
    );
  if (selected === 2)
    return (
      <TrafficTable
        events={data.traffic
          .filter((event) => event.decision === "denied")
          .slice(-12)
          .reverse()}
      />
    );
  if (selected === 3) return <RiskEvidence />;
  if (selected === 4) return <Response />;
  return <Recovery />;
}
