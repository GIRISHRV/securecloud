import { useState } from "react";
import { usePortal } from "../../app/PortalContext";
import { ActionButton } from "../../components/ActionButton";
import { Icon } from "../../components/Icon";
import { Panel } from "../../components/ui";
import { TrafficTable } from "../network/TrafficTable";

type Destination = "workloads" | "catalog" | "network" | "incidents";
export function Overview({
  navigate,
  onCreateTenant,
  onLoadDemo,
  busy,
}: {
  navigate: (view: Destination) => void;
  onCreateTenant: () => void;
  onLoadDemo: () => void;
  busy: boolean;
}) {
  const { scopedData: data, data: workspace, selectTenant } = usePortal();
  const [activeCommandIndex, setActiveCommandIndex] = useState(0);
  const stats = [
    { name: "Tenants", value: data.tenants.length, view: "workloads" as const },
    {
      name: "Workloads",
      value: data.workloads.length,
      view: "workloads" as const,
    },
    {
      name: "Denied connections",
      value: data.traffic.filter((e) => e.decision === "denied").length,
      view: "network" as const,
    },
    {
      name: "Active incidents",
      value: data.incidents.filter((i) => i.status !== "restored").length,
      view: "incidents" as const,
    },
  ];
  return (
    <>
      <div
        aria-label="Workspace commands"
        className="workspace-toolbar"
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          const buttons = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ),
          );
          const current = buttons.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          if (current < 0) return;
          event.preventDefault();
          const step = event.key === "ArrowRight" ? 1 : -1;
          const next = (current + step + buttons.length) % buttons.length;
          setActiveCommandIndex(next);
          buttons[next]?.focus();
        }}
        role="toolbar"
      >
        <ActionButton
          className="button command"
          onClick={onCreateTenant}
          tabIndex={activeCommandIndex === 0 ? 0 : -1}
          onFocus={() => setActiveCommandIndex(0)}
        >
          <Icon name="plus" size={16} />
          Create tenant
        </ActionButton>
        <ActionButton
          className="button command"
          onClick={() => navigate("catalog")}
          tabIndex={activeCommandIndex === 1 ? 0 : -1}
          onFocus={() => setActiveCommandIndex(1)}
        >
          <Icon name="box" size={16} />
          Deploy workload
        </ActionButton>
      </div>
      <section className="resource-summary" aria-label="Resource summary">
        {stats.map((s) => (
          <button
            className="resource-metric"
            key={s.name}
            onClick={() => navigate(s.view)}
          >
            <span>{s.name}</span>
            <strong>{s.value}</strong>
          </button>
        ))}
      </section>
      {!workspace.tenants.length && (
        <section className="workspace-empty">
          <h2>Build your first workspace</h2>
          <div className="workspace-empty-actions">
            <ActionButton className="button primary" onClick={onCreateTenant}>
              <Icon name="plus" size={16} />
              Create your first tenant
            </ActionButton>
            <ActionButton
              className="button"
              disabled={busy}
              onClick={onLoadDemo}
            >
              Load sample resources
            </ActionButton>
          </div>
        </section>
      )}
      {data.tenants.length > 0 && (
        <Panel
          title="Tenant workspaces"
          action={
            <ActionButton
              className="button compact"
              onClick={() => navigate("workloads")}
            >
              View all resources
            </ActionButton>
          }
        >
          <div
            className="table-scroll"
            role="region"
            aria-label="Tenant workspaces"
            tabIndex={0}
          >
            <table
              aria-label="Tenant workspaces"
              className="console-data-table"
            >
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Workloads</th>
                  <th>Running</th>
                </tr>
              </thead>
              <tbody>
                {data.tenants.map((t) => {
                  const workloads = data.workloads.filter(
                    (w) => w.tenantId === t.id,
                  );
                  return (
                    <tr key={t.id}>
                      <td>
                        <ActionButton
                          className="button compact link-button"
                          onClick={() => {
                            selectTenant(t.id);
                            navigate("workloads");
                          }}
                        >
                          {t.name}
                        </ActionButton>
                      </td>
                      <td>{t.description || "—"}</td>
                      <td>{workloads.length}</td>
                      <td>
                        {workloads.filter((w) => w.status === "running").length}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!data.tenants.length && (
            <p className="empty-table-message">No tenants in this workspace.</p>
          )}
        </Panel>
      )}
      {data.traffic.length > 0 && (
        <Panel
          title="Recent connection activity"
          action={
            <ActionButton
              className="button compact"
              onClick={() => navigate("network")}
            >
              View activity
            </ActionButton>
          }
        >
          <TrafficTable events={data.traffic.slice(-4).reverse()} compact />
        </Panel>
      )}
    </>
  );
}
