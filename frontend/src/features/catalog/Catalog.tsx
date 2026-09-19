import { ActionButton } from "../../components/ActionButton";
import { useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { Badge, Modal } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { templates } from "../../domain/seed";
import type { TenantId, TemplateId } from "../../domain/models";

export function Catalog({ onCreateTenant }: { onCreateTenant: () => void }) {
  const { service, data, tenantId: activeTenant } = usePortal();
  const [templateId, setTemplateId] = useState<TemplateId | null>(null);
  const [tenantId, setTenantId] = useState<TenantId>(
    activeTenant || data.tenants[0]?.id || "",
  );
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const { error, busy, run } = useAction();
  const selected = templates.find((t) => t.id === templateId);
  return (
    <>
      {!data.tenants.length && (
        <div className="catalog-prerequisite">
          <div>
            <strong>Create a tenant before deploying</strong>
          </div>
          <ActionButton className="button primary" onClick={onCreateTenant}>
            Create tenant
          </ActionButton>
        </div>
      )}
      {notice && (
        <p className="success-note" role="status">
          <Icon name="check" size={18} />
          {notice}
        </p>
      )}
      <div
        className="table-scroll"
        role="region"
        aria-label="Approved templates"
        tabIndex={0}
      >
        <table
          aria-label="Approved templates"
          className="console-data-table catalog-table"
        >
          <thead>
            <tr>
              <th>Template</th>
              <th>Status</th>
              <th>CPU limit</th>
              <th>Memory</th>
              <th>Port</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.id}>
                <td>
                  <div className="catalog-template-name">
                    <Icon name={t.id} size={20} />
                    <strong>{t.name}</strong>
                  </div>
                  <p>{t.description}</p>
                </td>
                <td>
                  <Badge tone="green">Approved</Badge>
                </td>
                <td>{t.cpu} vCPU</td>
                <td>{t.memory} MiB</td>
                <td>TCP {t.port}</td>
                <td>
                  <ActionButton
                    className="button compact link-button"
                    disabled={!data.tenants.length}
                    onClick={() => {
                      setTenantId(activeTenant || data.tenants[0]?.id || "");
                      setTemplateId(t.id);
                      setName("");
                      setNotice("");
                    }}
                  >
                    <Icon name="plus" size={17} />
                    Deploy{" "}
                    {t.id === "database"
                      ? "database"
                      : t.id === "api"
                        ? "API"
                        : "web app"}
                  </ActionButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && (
        <Modal
          title={`Deploy ${selected.name.toLowerCase()}`}
          onClose={() => setTemplateId(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(
                () => service.deploy(tenantId, selected.id, name),
                () => {
                  setNotice(
                    `${name.trim()} deployed to ${data.tenants.find((t) => t.id === tenantId)?.name} in the simulation.`,
                  );
                  setTemplateId(null);
                },
              );
            }}
          >
            <p className="muted">
              Create a simulated workload from the approved catalog.
            </p>
            <label className="field">
              Tenant
              <select
                aria-label="Tenant"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value as TenantId)}
              >
                {data.tenants.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Workload name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`my-${selected.id}-01`}
                required
                minLength={3}
                maxLength={40}
                aria-describedby="name-help"
                autoComplete="off"
              />
            </label>
            <p id="name-help" className="field-help">
              3–40 lowercase letters, numbers, or hyphens. Start with a letter.
            </p>
            <div className="deploy-summary">
              <span>{selected.cpu} vCPU</span>
              <span>{selected.memory} MiB</span>
              <span>TCP {selected.port}</span>
            </div>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <div className="modal-actions">
              <ActionButton
                type="button"
                className="button"
                onClick={() => setTemplateId(null)}
              >
                Cancel
              </ActionButton>
              <ActionButton className="button primary" disabled={busy}>
                Create demo workload
                <Icon name="arrow" size={16} />
              </ActionButton>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
