import { ActionButton } from "../../components/ActionButton";
import { useEffect, useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { Badge, Modal } from "../../components/ui";
import { Icon } from "../../components/Icon";
import { templates } from "../../domain/seed";
import type {
  CatalogDefinition,
  StackId,
  TenantId,
  TemplateId,
} from "../../domain/models";

export function Catalog({ onCreateTenant }: { onCreateTenant: () => void }) {
  const { service, data, mode, tenantId: activeTenant } = usePortal();
  const [templateId, setTemplateId] = useState<TemplateId | null>(null);
  const [stackId, setStackId] = useState<StackId | null>(null);
  const [tenantId, setTenantId] = useState<TenantId>(
    activeTenant || data.tenants[0]?.id || "",
  );
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const [catalog, setCatalog] = useState<CatalogDefinition | null>(null);
  const [catalogError, setCatalogError] = useState(false);
  const { error, busy, run } = useAction();
  const approvedTemplates = catalog?.templates ?? templates;
  const selected = approvedTemplates.find((t) => t.id === templateId);
  const selectedStack = catalog?.stacks.find((stack) => stack.id === stackId);

  useEffect(() => {
    let active = true;
    service.getCatalog().then(
      (value) => {
        if (active) setCatalog(value);
      },
      () => {
        if (active) setCatalogError(true);
      },
    );
    return () => {
      active = false;
    };
  }, [service]);
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
            {approvedTemplates.map((t) => (
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
      <h2 className="catalog-heading">Application stacks</h2>
      {catalogError ? (
        <p className="error" role="alert">
          Application stack definitions are unavailable.
        </p>
      ) : (
        <div
          className="table-scroll"
          role="region"
          aria-label="Approved application stacks"
          tabIndex={0}
        >
          <table
            aria-label="Approved application stacks"
            className="console-data-table catalog-table"
          >
            <thead>
              <tr>
                <th>Stack</th>
                <th>Status</th>
                <th>Services</th>
                <th>Version</th>
                <th>Deployment</th>
              </tr>
            </thead>
            <tbody>
              {(catalog?.stacks ?? []).map((stack) => (
                <tr key={stack.id}>
                  <td>
                    <div className="catalog-template-name">
                      <Icon
                        name={stack.id === "retail-stack" ? "web" : "api"}
                        size={20}
                      />
                      <strong>{stack.name}</strong>
                    </div>
                    <p>{stack.workflow}</p>
                  </td>
                  <td>
                    <Badge
                      tone={stack.status === "validated" ? "blue" : "neutral"}
                    >
                      {stack.status}
                    </Badge>
                  </td>
                  <td>{stack.services.length}</td>
                  <td>{stack.version}</td>
                  <td>
                    {stack.deployment_enabled ? (
                      <ActionButton
                        className="button compact link-button"
                        disabled={!data.tenants.length}
                        onClick={() => {
                          setTenantId(
                            activeTenant || data.tenants[0]?.id || "",
                          );
                          setStackId(stack.id);
                          setName("");
                          setNotice("");
                        }}
                      >
                        <Icon name="plus" size={17} />
                        Deploy stack
                      </ActionButton>
                    ) : (
                      "Adapter pending"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selectedStack && (
        <Modal
          title={`Deploy ${selectedStack.name.toLowerCase()}`}
          onClose={() => setStackId(null)}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(
                () => service.deployStack(tenantId, selectedStack.id, name),
                () => {
                  setNotice(
                    `${selectedStack.name} is running in ${data.tenants.find((tenant) => tenant.id === tenantId)?.name}.`,
                  );
                  setStackId(null);
                },
              );
            }}
          >
            <label className="field">
              Tenant
              <select
                aria-label="Tenant"
                value={tenantId}
                onChange={(event) =>
                  setTenantId(event.target.value as TenantId)
                }
              >
                {data.tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Stack name
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="retail-app"
                required
                minLength={3}
                maxLength={40}
                pattern="[a-z][a-z0-9-]{2,39}"
                autoComplete="off"
              />
            </label>
            <div className="deploy-summary">
              <span>{selectedStack.services.length} services</span>
              <span>{selectedStack.version}</span>
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
                onClick={() => setStackId(null)}
              >
                Cancel
              </ActionButton>
              <ActionButton className="button primary" disabled={busy}>
                {busy ? "Provisioning stack…" : "Deploy stack"}
                <Icon name="arrow" size={16} />
              </ActionButton>
            </div>
          </form>
        </Modal>
      )}
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
                    mode === "api"
                      ? `${name.trim()} is running in ${data.tenants.find((t) => t.id === tenantId)?.name}.`
                      : `${name.trim()} deployed to ${data.tenants.find((t) => t.id === tenantId)?.name} in the simulation.`,
                  );
                  setTemplateId(null);
                },
              );
            }}
          >
            <p className="muted">
              {mode === "api"
                ? "Provision a bounded workload from the approved catalog."
                : "Create a simulated workload from the approved catalog."}
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
                {busy
                  ? "Waiting for observed state…"
                  : mode === "api"
                    ? "Deploy workload"
                    : "Create demo workload"}
                <Icon name="arrow" size={16} />
              </ActionButton>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
