import { useState } from "react";
import { usePortal } from "../../app/PortalContext";
import { Icon } from "../../components/Icon";
import { templates } from "../../domain/seed";
import { Empty } from "../../components/ui";
import { WorkloadInspector } from "../workloads/Workloads";

export function Topology({ compact = false }: { compact?: boolean }) {
  const { scopedData: data } = usePortal();
  const [selected, setSelected] = useState<string | null>(null);
  const activeWorkloads = data.workloads.filter(
    (workload) => workload.status !== "stopped",
  );
  const visibleTenants = data.tenants.filter((tenant) =>
    activeWorkloads.some((workload) => workload.tenantId === tenant.id),
  );
  if (!visibleTenants.length)
    return (
      <Empty title="Your network starts here">
        Create tenants and deploy workloads to see their network topology. Load
        demo to explore an example.
      </Empty>
    );
  return (
    <>
      <div className={`topology ${compact ? "compact-topology" : ""}`}>
        {visibleTenants.map((tenant) => {
          const workloads = templates.flatMap((template) =>
            activeWorkloads.filter(
              (workload) =>
                workload.tenantId === tenant.id &&
                workload.templateId === template.id,
            ),
          );
          return (
            <section className="tenant-zone" key={tenant.id}>
              <div className="zone-heading">
                <span className={`tenant-avatar small ${tenant.id}`}>
                  {tenant.name[0]}
                </span>
                <strong>{tenant.name}</strong>
                <span className="zone-caption">
                  {workloads.length} workload{workloads.length === 1 ? "" : "s"}
                </span>
              </div>
              <div className="topology-flow">
                {workloads.map((workload, index) => {
                  const previous = workloads[index - 1];
                  const port =
                    previous?.templateId === "web" && workload.templateId === "api"
                      ? "8080"
                      : previous?.templateId === "api" && workload.templateId === "database"
                        ? "5432"
                        : null;
                  return (
                    <div className="topology-step" key={workload.id}>
                      {port && (
                        <div className="topology-link" aria-label={`TCP ${port}`}>
                          <span>{port}</span>
                        </div>
                      )}
                      <button
                        title={`Inspect ${workload.name}`}
                        className={`topology-node ${workload.quarantined ? "quarantine-node" : ""} ${workload.status === "stopped" ? "stopped-node" : ""}`}
                        onClick={() => setSelected(workload.id)}
                      >
                        <span className={`small-template ${workload.templateId}`}>
                          <Icon name={workload.templateId} size={18} />
                        </span>
                        <span className="node-name">{workload.name}</span>
                        <span
                          className={`node-dot ${workload.quarantined ? "red-dot" : workload.status === "stopped" ? "gray-dot" : ""}`}
                        />
                        <span className="node-state">
                          {workload.quarantined ? "quarantined" : workload.status}
                        </span>
                      </button>
                    </div>
                  );
                })}
                {!workloads.length && <span className="zone-empty">No workloads</span>}
              </div>
            </section>
          );
        })}
      </div>
      <div className="topology-legend">
        <span>
          <i className="legend-line" />
          Approved path
        </span>
        <span>
          <i className="node-dot" />
          Running
        </span>
        <span>
          <i className="node-dot red-dot" />
          Quarantined
        </span>
      </div>
      {selected && (
        <WorkloadInspector id={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}
