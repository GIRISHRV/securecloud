import { ActionButton } from "../../components/ActionButton";
import { useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { Badge, Panel } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { reasonLabels } from "../../domain/policy";
import type { TrafficEvent } from "../../domain/models";
import { Topology } from "./Topology";
import { TrafficTable } from "./TrafficTable";

export function Network({ onIncidents }: { onIncidents: () => void }) {
  const { data, service, scopedData } = usePortal();
  const [source, setSource] = useState(
    scopedData.workloads.find((w) => w.templateId === "web")?.id ??
      scopedData.workloads[0]?.id ??
      "",
  );
  const [destination, setDestination] = useState(
    scopedData.workloads.find((w) => w.templateId === "api")?.id ??
      scopedData.workloads[1]?.id ??
      "",
  );
  const [port, setPort] = useState("8080");
  const [result, setResult] = useState<TrafficEvent | null>(null);
  const { error, busy, run } = useAction();
  const activeIncidents = scopedData.incidents.filter(
    (i) => i.status !== "restored",
  );
  const validSource = scopedData.workloads.some((w) => w.id === source)
    ? source
    : "";
  const validDestination = data.workloads.some((w) => w.id === destination)
    ? destination
    : "";
  function send(count: number) {
    void run(async () => {
      for (let i = 0; i < count; i++)
        setResult(
          await service.simulate(validSource, validDestination, Number(port)),
        );
    });
  }
  function preset(crossTenant: boolean) {
    const src = scopedData.workloads.find(
      (w) =>
        w.templateId === "web" &&
        data.workloads.some(
          (d) =>
            d.templateId === "api" &&
            (crossTenant
              ? d.tenantId !== w.tenantId
              : d.tenantId === w.tenantId),
        ),
    );
    const dst = data.workloads.find(
      (w) =>
        (crossTenant
          ? w.tenantId !== src?.tenantId
          : w.tenantId === src?.tenantId) && w.templateId === "api",
    );
    setSource(src?.id ?? "");
    setDestination(src ? (dst?.id ?? "") : "");
    setPort("8080");
    setResult(null);
  }
  return (
    <>
      <Panel
        title="Tenant network topology"
      >
        <Topology />
      </Panel>
      <div className="network-bottom">
        <Panel title={service.mode === "api" ? "Live enforcement" : "Connection simulator"}>
          {service.mode === "api" ? (
            <div className="live-policy-summary">
              <strong>Cilium network policy is active</strong>
              <p>
                Approved service paths continue to operate. Denied connections
                shown below are observed Hubble verdicts from the cluster.
              </p>
              <p>
                Controlled security scenarios run outside this portal and cannot
                target arbitrary systems.
              </p>
            </div>
          ) : (
          <div className="simulator">
            <div className="preset-row">
              <span>Presets</span>
              <button className="chip" onClick={() => preset(false)}>
                Approved local path
              </button>
              <button className="chip" onClick={() => preset(true)}>
                Cross-tenant attempt
              </button>
            </div>
            {scopedData.workloads.length < 1 && (
              <p className="info-note">
                Deploy workloads to this tenant, or load the demo, before
                simulating connections.
              </p>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(1);
              }}
            >
              <div className="connection-form">
                <label className="field">
                  Source workload
                  <select
                    value={validSource}
                    onChange={(e) => {
                      setSource(e.target.value);
                      setResult(null);
                    }}
                    required
                  >
                    <option value="" disabled>
                      Select source
                    </option>
                    {scopedData.workloads.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name} (
                        {data.tenants.find((t) => t.id === w.tenantId)?.name})
                      </option>
                    ))}
                  </select>
                </label>
                <span className="form-arrow">
                  <Icon name="arrow" />
                </span>
                <label className="field">
                  Destination workload
                  <select
                    value={validDestination}
                    onChange={(e) => {
                      setDestination(e.target.value);
                      setResult(null);
                    }}
                    required
                  >
                    <option value="" disabled>
                      Select destination
                    </option>
                    {data.workloads.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name} (
                        {data.tenants.find((t) => t.id === w.tenantId)?.name})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field port-field">
                  TCP port
                  <input
                    type="number"
                    min="1"
                    max="65535"
                    step="1"
                    value={port}
                    onChange={(e) => {
                      setPort(e.target.value);
                      setResult(null);
                    }}
                    required
                  />
                </label>
              </div>
              <div className="simulator-actions">
                <ActionButton
                  className="button primary"
                  disabled={busy || !validSource || !validDestination}
                >
                  <Icon name="activity" size={17} />
                  Simulate connection
                </ActionButton>
                <ActionButton
                  type="button"
                  className="button"
                  disabled={busy || !validSource || !validDestination}
                  onClick={() => send(3)}
                >
                  Send 3 attempts
                </ActionButton>
              </div>
            </form>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <div aria-live="polite">
              {result && (
                <div className={`decision-result ${result.decision}`}>
                  <Badge
                    tone={
                      result.decision === "allowed"
                        ? "green"
                        : result.decision === "denied"
                          ? "red"
                          : "amber"
                    }
                  >
                    {result.decision}
                  </Badge>
                  <strong>{reasonLabels[result.reason]}</strong>
                  <small>
                    {result.sourceName} → {result.destinationName}:{result.port}{" "}
                    · Policy result
                  </small>
                </div>
              )}
            </div>
          </div>
          )}
        </Panel>
        <Panel title={service.mode === "api" ? "Policy controls" : "Detection rule"}>
          {service.mode === "api" ? (
            <div className="live-policy-summary">
              <strong>Default deny</strong>
              <p>Web workloads can reach only their tenant API on TCP 8080.</p>
              <p>API workloads can reach only their tenant database on TCP 5432.</p>
              <p>Cross-tenant workload traffic is denied and retained as evidence.</p>
            </div>
          ) : (
          <div className="rule-content">
            <span className="rule-number">
              03 <small>attempts / 60 seconds</small>
            </span>
            <p>
              Three unapproved or cross-tenant denials from the same source
              raise one incident in a sliding window.
            </p>
            <p>
              Quarantine denials and stopped endpoints do not count. Quarantine
              is an explicit operator action.
            </p>
            <button className="text-button" onClick={onIncidents}>
              View incidents ({activeIncidents.length} active)
              <Icon name="arrow" size={16} />
            </button>
          </div>
          )}
        </Panel>
      </div>
      <Panel
        title={service.mode === "api" ? "Live traffic evidence" : "Traffic evidence"}
      >
        <TrafficTable events={scopedData.traffic.slice(-30).reverse()} />
      </Panel>
    </>
  );
}
