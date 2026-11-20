import { ActionButton } from "../../components/ActionButton";
import { useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { Badge, Empty, Panel, time } from "../../components/ui";
import { Icon } from "../../components/Icon";
import type { Incident } from "../../domain/models";
import { TrafficTable } from "../network/TrafficTable";

export const incidentTone = (status: Incident["status"]) =>
  status === "restored"
    ? "green"
    : status === "quarantined"
      ? "red"
      : status === "review"
        ? "blue"
        : "amber";
export function Incidents({ onNetwork }: { onNetwork: () => void }) {
  const { scopedData: data, service } = usePortal();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "restored">("all");
  const { error, busy, run } = useAction();
  const incidents = data.incidents.filter(
    (i) =>
      filter === "all" ||
      (filter === "active" ? i.status !== "restored" : i.status === "restored"),
  );
  const selected = incidents.find((i) => i.id === selectedId) ?? incidents[0];
  return (
    <>
      <div className="incident-summary">
        <div>
          <Icon name="alert" size={22} />
          <strong>
            {data.incidents.filter((i) => i.status !== "restored").length}
          </strong>
          <span>Active incidents</span>
        </div>
        <div>
          <Icon name="shield" size={22} />
          <strong>{data.workloads.filter((w) => w.quarantined).length}</strong>
          <span>Quarantined workloads</span>
        </div>
        <div>
          <Icon name="check" size={22} />
          <strong>
            {data.incidents.filter((i) => i.status === "restored").length}
          </strong>
          <span>Restored incidents</span>
        </div>
      </div>
      <div className="tab-row" aria-label="Incident filters">
        {(["all", "active", "restored"] as const).map((value) => (
          <button
            key={value}
            aria-pressed={filter === value}
            className={filter === value ? "selected" : ""}
            onClick={() => setFilter(value)}
          >
            {value === "all"
              ? "All incidents"
              : value === "active"
                ? "Active"
                : "Restored"}
          </button>
        ))}
      </div>
      {!selected ? (
        <section className="panel">
          <Empty
            title={
              data.incidents.length
                ? "No incidents in this view"
                : "No incidents yet"
            }
          >
            {service.mode === "api"
              ? "Detector findings from observed Hubble traffic will appear here."
              : "Use the Network Map to send three cross-tenant attempts within 60 seconds. The resulting alert will appear here."}
          </Empty>
          <div className="empty-action">
            <ActionButton className="button primary" onClick={onNetwork}>
              {service.mode === "api"
                ? "Open network evidence"
                : "Open connection simulator"}
              <Icon name="arrow" size={16} />
            </ActionButton>
          </div>
        </section>
      ) : (
        <div className="incident-layout">
          <div className="incident-list">
            {incidents.map((incident) => (
              <button
                className={`incident-card ${selected.id === incident.id ? "selected" : ""}`}
                key={incident.id}
                onClick={() => setSelectedId(incident.id)}
                aria-pressed={selected.id === incident.id}
              >
                <div>
                  <span className="incident-id">
                    INC-{incident.id.slice(0, 6).toUpperCase()}
                  </span>
                  <Badge tone={incidentTone(incident.status)}>
                    {incident.status}
                  </Badge>
                </div>
                <strong>{incident.sourceName}</strong>
                <p>{incident.reason}</p>
                <small>
                  {data.tenants.find((t) => t.id === incident.tenantId)?.name} ·{" "}
                  {time(incident.createdAt)}
                </small>
              </button>
            ))}
          </div>
          <div className="incident-detail">
            <Panel
              title="Incident response"
              description={`${selected.sourceName} · ${data.tenants.find((t) => t.id === selected.tenantId)?.name} tenant`}
              action={
                <Badge tone={incidentTone(selected.status)}>
                  {selected.status}
                </Badge>
              }
            >
              <div className="response-body">
                <div className="response-stages">
                  {(
                    ["alert", "quarantined", "review", "restored"] as const
                  ).map((stage, index) => (
                    <span
                      key={stage}
                      className={
                        ["alert", "quarantined", "review", "restored"].indexOf(
                          selected.status,
                        ) >= index
                          ? "reached"
                          : ""
                      }
                    >
                      <b>{index + 1}</b>
                      {stage}
                    </span>
                  ))}
                </div>
                <p className="info-note">
                  {selected.status === "alert"
                    ? service.mode === "api"
                      ? "The detector correlated an anomalous graph edge with explicit policy-denial evidence. Quarantine withdraws this workload's previously approved access."
                      : "The rule detected suspicious attempts. Quarantine withdraws previously approved access and may disrupt dependent services."
                    : selected.status === "restored"
                      ? service.mode === "api"
                        ? "The original static intents apply again. Verify the approved path against live network evidence."
                        : "The original static intents apply again. Verify the approved path in the simulator. Stopped workloads remain stopped."
                      : service.mode === "api"
                        ? "Quarantine remains active through reconciliation and pod replacement until an authorized restore."
                        : "Quarantine remains active through review and page refresh. Test the previously approved path to observe its simulated denial."}
                </p>
                {error && (
                  <p className="error" role="alert">
                    {error}
                  </p>
                )}
                <div className="response-actions">
                  {selected.status === "alert" && (
                    <ActionButton
                      className="button danger"
                      disabled={busy}
                      onClick={() =>
                        void run(() => service.quarantine(selected.id))
                      }
                    >
                      <Icon name="shield" size={16} />
                      Quarantine workload
                    </ActionButton>
                  )}
                  {selected.status === "quarantined" && (
                    <ActionButton
                      className="button primary"
                      disabled={busy}
                      onClick={() =>
                        void run(() => service.review(selected.id))
                      }
                    >
                      Start review
                      <Icon name="arrow" size={16} />
                    </ActionButton>
                  )}
                  {selected.status === "review" && (
                    <ActionButton
                      className="button primary"
                      disabled={busy}
                      onClick={() =>
                        void run(() => service.restore(selected.id))
                      }
                    >
                      <Icon name="check" size={16} />
                      Restore workload
                    </ActionButton>
                  )}
                  <ActionButton className="button" onClick={onNetwork}>
                    {service.mode === "api"
                      ? "View network evidence"
                      : "Test a connection"}
                    <Icon name="arrow" size={16} />
                  </ActionButton>
                </div>
              </div>
            </Panel>
            <Panel
              title="Incident trace"
              description={
                service.mode === "api"
                  ? "From the first observed flow to the current response."
                  : "From the first attempt to the current response. Simulation only."
              }
            >
              <ol className="trace">
                {selected.trace.map((step, index) => (
                  <li key={`${index}-${step.at}`}>
                    <span className="trace-dot">
                      <Icon
                        name={
                          index === 0
                            ? "network"
                            : index === 1
                              ? "shield"
                              : index === 2
                                ? "alert"
                                : "check"
                        }
                        size={16}
                      />
                    </span>
                    <div>
                      <div className="trace-heading">
                        <h3>{step.title}</h3>
                        <time>{time(step.at)}</time>
                      </div>
                      <p>{step.detail}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </Panel>
            <Panel
              title="Triggering evidence"
              description="Preserved with the incident, including after workload deletion."
            >
              <TrafficTable events={selected.evidence} />
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
