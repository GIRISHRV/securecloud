import { ActionButton } from "../../components/ActionButton";
import { useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { Badge, Empty, Modal } from "../../components/ui";
import { Icon } from "../../components/Icon";
import type { Workload } from "../../domain/models";
import { templates } from "../../domain/seed";

export function WorkloadBadge({ workload }: { workload: Workload }) {
  return (
    <div className="status-group">
      <Badge tone={workload.status === "running" ? "green" : "neutral"}>
        {workload.status}
      </Badge>
      {workload.quarantined && <Badge tone="red">quarantined</Badge>}
    </div>
  );
}
export function WorkloadInspector({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const { data, service } = usePortal();
  const workload = data.workloads.find((w) => w.id === id);
  const [action, setAction] = useState<"stop" | "delete" | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const { error, busy, run } = useAction();
  if (!workload) return null;
  const template = templates.find((t) => t.id === workload.templateId)!;
  const active = data.incidents.some(
    (i) => i.sourceId === id && i.status !== "restored",
  );
  return (
    <Modal title="Workload details" onClose={onClose}>
      <div className="detail-identity">
        <span className={`template-icon ${workload.templateId}`}>
          <Icon name={workload.templateId} size={25} />
        </span>
        <div>
          <h3>{workload.name}</h3>
          <p>
            {data.tenants.find((t) => t.id === workload.tenantId)?.name} /{" "}
            {template.name}
          </p>
        </div>
      </div>
      {!action && (
        <>
          <WorkloadBadge workload={workload} />
          <dl className="detail-grid">
            <div>
              <dt>CPU limit</dt>
              <dd>{template.cpu} vCPU</dd>
            </div>
            <div>
              <dt>Memory limit</dt>
              <dd>{template.memory} MiB</dd>
            </div>
            <div>
              <dt>Service port</dt>
              <dd>TCP {template.port}</dd>
            </div>
            <div>
              <dt>Policy</dt>
              <dd>Default deny + tenant intents</dd>
            </div>
            <div className="full">
              <dt>Demo workload ID</dt>
              <dd className="mono">{workload.id}</dd>
            </div>
          </dl>
          <p className="info-note">
            This is a browser simulation. No container or cloud resource has
            been provisioned.
          </p>
          {active && (
            <p className="warning-note">
              An active incident prevents deletion. Complete quarantine, review,
              and restore first. Stopping preserves quarantine.
            </p>
          )}
        </>
      )}
      {action ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(
              () =>
                action === "stop"
                  ? service.stop(workload.tenantId, id, confirmation)
                  : service.deleteWorkload(workload.tenantId, id, confirmation),
              onClose,
            );
          }}
        >
          <label className="field">
            Type <strong>{workload.name}</strong> to {action}
            <input
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="off"
            />
          </label>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <ActionButton
              type="button"
              className="button"
              onClick={() => setAction(null)}
            >
              Cancel
            </ActionButton>
            <ActionButton
              className="button danger"
              disabled={busy || confirmation !== workload.name}
            >
              Confirm {action}
            </ActionButton>
          </div>
        </form>
      ) : (
        <div className="modal-actions">
          <ActionButton
            className="button"
            disabled={workload.status === "stopped"}
            onClick={() => setAction("stop")}
          >
            <Icon name="stop" size={16} />
            Stop workload
          </ActionButton>
          <ActionButton
            className="button danger-outline"
            disabled={active}
            onClick={() => setAction("delete")}
          >
            <Icon name="trash" size={16} />
            Delete workload
          </ActionButton>
        </div>
      )}
    </Modal>
  );
}
export function Workloads({
  onDeploy,
  onCreateTenant,
}: {
  onDeploy: () => void;
  onCreateTenant: () => void;
}) {
  const { data, tenantId: tenant, selectTenant: setTenant } = usePortal();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const workloads = data.workloads.filter(
    (w) =>
      (!tenant || w.tenantId === tenant) &&
      w.name.includes(query.toLowerCase()),
  );
  return (
    <>
      <div className="resource-commandbar">
        <span>{data.tenants.length} tenants in this workspace</span>
        <ActionButton className="button primary" onClick={onCreateTenant}>
          <Icon name="plus" size={16} />
          Create tenant
        </ActionButton>
      </div>
      {!data.tenants.length && (
        <section className="panel">
          <Empty title="No tenants yet">
            Create a tenant to organize your workloads, or use Load demo in the
            header to explore the sample workspace.
          </Empty>
        </section>
      )}
      <div className="tenant-cards">
        {data.tenants.map((t) => {
          const items = data.workloads.filter((w) => w.tenantId === t.id);
          return (
            <button
              key={t.id}
              className={`tenant-card ${tenant === t.id ? "selected" : ""}`}
              onClick={() => setTenant(tenant === t.id ? "" : t.id)}
              aria-pressed={tenant === t.id}
            >
              <span className={`tenant-avatar ${t.id}`}>
                {t.name.slice(0, 1)}
              </span>
              <span>
                <strong>{t.name}</strong>
                <span className="muted">
                  {t.description || "Tenant workspace"}
                </span>
              </span>
              <span className="tenant-total">
                {items.length}
                <small>workloads</small>
              </span>
            </button>
          );
        })}
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              Tenant workloads <span className="count">{workloads.length}</span>
            </h2>
          </div>
          <ActionButton
            className="button primary"
            onClick={onDeploy}
            disabled={!data.tenants.length}
          >
            <Icon name="plus" size={16} />
            Deploy workload
          </ActionButton>
        </div>
        <div className="table-toolbar">
          <label className="search-field">
            <Icon name="search" size={17} />
            <input
              aria-label="Search workloads"
              placeholder="Search workloads…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label className="inline-field">
            Tenant
            <select value={tenant} onChange={(e) => setTenant(e.target.value)}>
              <option value="">All tenants</option>
              {data.tenants.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {workloads.length ? (
          <div className="table-scroll">
            <table className="workload-table">
              <thead>
                <tr>
                  <th>Workload</th>
                  <th>Tenant</th>
                  <th>Status</th>
                  <th>Resources</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {workloads.map((w) => {
                  const template = templates.find(
                    (t) => t.id === w.templateId,
                  )!;
                  return (
                    <tr key={w.id}>
                      <td>
                        <div className="workload-cell">
                          <span className={`small-template ${w.templateId}`}>
                            <Icon name={w.templateId} size={18} />
                          </span>
                          <span>
                            <button
                              className="text-button workload-name"
                              onClick={() => setSelected(w.id)}
                            >
                              {w.name}
                            </button>
                            <small>{template.name}</small>
                          </span>
                        </div>
                      </td>
                      <td>
                        <span className={`tenant-label ${w.tenantId}`}>
                          {data.tenants.find((t) => t.id === w.tenantId)?.name}
                        </span>
                      </td>
                      <td>
                        <WorkloadBadge workload={w} />
                      </td>
                      <td className="resource-text">
                        {template.cpu} vCPU <span>·</span> {template.memory} MiB
                      </td>
                      <td>
                        <ActionButton
                          className="button compact"
                          onClick={() => setSelected(w.id)}
                          aria-label={`Inspect ${w.name}`}
                        >
                          Inspect
                          <Icon name="chevron" size={14} />
                        </ActionButton>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No workloads found">
            Try another search or deploy a catalog template.
          </Empty>
        )}
        <div className="panel-footer">
          {workloads.length} workload{workloads.length === 1 ? "" : "s"} shown{" "}
          <span>Demo quota: 12 per tenant</span>
        </div>
      </section>
      {selected && (
        <WorkloadInspector id={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}
