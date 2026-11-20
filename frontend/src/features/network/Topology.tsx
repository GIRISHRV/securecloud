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
          const workloadGroups = templates.map((template) => ({
            template,
            workloads: activeWorkloads.filter(
              (workload) =>
                workload.tenantId === tenant.id &&
                workload.templateId === template.id,
            ),
          }));
          const workloadCount = workloadGroups.reduce(
            (total, group) => total + group.workloads.length,
            0,
          );
          return (
            <section className="tenant-zone" key={tenant.id}>
              <div className="zone-heading">
                <span className={`tenant-avatar small ${tenant.id}`}>
                  {tenant.name[0]}
                </span>
                <strong>{tenant.name}</strong>
                <span className="zone-caption">
                  {workloadCount} workload{workloadCount === 1 ? "" : "s"}
                </span>
              </div>
              <div className="topology-flow">
                {workloadGroups.map(({ template, workloads }) => (
                  <section className="topology-tier" key={template.id}>
                    <header className="topology-tier-heading">
                      <span>{template.name}</span>
                      <span>{workloads.length}</span>
                    </header>
                    <div className="topology-tier-nodes">
                      {workloads.map((workload) => (
                        <button
                          key={workload.id}
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
                      ))}
                      {!workloads.length && (
                        <span className="zone-empty">No workloads</span>
                      )}
                    </div>
                  </section>
                ))}
              </div>
            </section>
          );
        })}
      </div>
      <div className="topology-legend">
        <span>
          <i className="legend-group" />
          Grouped by catalog role
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
