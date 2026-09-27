import { useState } from "react";
import { usePortal } from "../../app/PortalContext";
import { Icon } from "../../components/Icon";
import { templates } from "../../domain/seed";
import { Empty } from "../../components/ui";
import { WorkloadInspector } from "../workloads/Workloads";

export function Topology({ compact = false }: { compact?: boolean }) {
  const { scopedData: data } = usePortal();
  const [selected, setSelected] = useState<string | null>(null);
  if (!data.tenants.length)
    return (
      <Empty title="Your network starts here">
        Create tenants and deploy workloads to see their network topology. Load
        demo to explore an example.
      </Empty>
    );
  return (
    <>
      <div className={`topology ${compact ? "compact-topology" : ""}`}>
        {data.tenants.map((tenant) => (
          <div className={`tenant-zone ${tenant.id}`} key={tenant.id}>
            <div className="zone-heading">
              <span className={`tenant-avatar small ${tenant.id}`}>
                {tenant.name[0]}
              </span>
              <strong>{tenant.name}</strong>
              <span className="zone-caption">Tenant boundary</span>
            </div>
            <div className="topology-lanes">
              {templates.map((template, index) => (
                <div className="topology-group" key={template.id}>
                  <div className="topology-nodes">
                    {data.workloads
                      .filter(
                        (w) =>
                          w.tenantId === tenant.id &&
                          w.templateId === template.id,
                      )
                      .map((w) => (
                        <button
                          key={w.id}
                          title={`Inspect ${w.name}`}
                          className={`topology-node ${w.quarantined ? "quarantine-node" : ""} ${w.status === "stopped" ? "stopped-node" : ""}`}
                          onClick={() => setSelected(w.id)}
                        >
                          <span className={`small-template ${template.id}`}>
                            <Icon name={template.id} size={18} />
                          </span>
                          <span className="node-name">{w.name}</span>
                          <span
                            className={`node-dot ${w.quarantined ? "red-dot" : w.status === "stopped" ? "gray-dot" : ""}`}
                          />
                          <span className="node-state">
                            {w.quarantined ? "Quarantined" : w.status}
                          </span>
                        </button>
                      ))}
                    {!data.workloads.some(
                      (w) =>
                        w.tenantId === tenant.id &&
                        w.templateId === template.id,
                    ) && (
                      <div className="missing-node">
                        No {template.id} workload
                      </div>
                    )}
                  </div>
                  {index < 2 && (
                    <div className="topology-link">
                      <span>{index === 0 ? "8080" : "5432"}</span>
                      <div />
                      <Icon name="chevron" size={14} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
        <div className="boundary-label">
          <Icon name="shield" size={14} />
          Cross-tenant traffic denied by the model
        </div>
      </div>
      <div className="topology-legend">
        <span>
          <i className="legend-line" />
          Static intended path (TCP)
        </span>
        <span>
          <i className="node-dot" />
          Running
        </span>
        <span>
          <i className="node-dot red-dot" />
          Quarantined
        </span>
        <span>
          <i className="node-dot gray-dot" />
          Stopped
        </span>
      </div>
      {selected && (
        <WorkloadInspector id={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}
