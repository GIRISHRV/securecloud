import { ActionButton } from "../../components/ActionButton";
import { useState } from "react";
import { useAction, usePortal } from "../../app/PortalContext";
import { Modal } from "../../components/ui";

export function CreateTenant({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { service, selectTenant } = usePortal();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const { error, busy, run } = useAction();
  return (
    <Modal title="Create tenant" onClose={onClose}>
      <p className="muted">
        Organize workloads in a separate tenant workspace. This creates a local
        simulated tenant.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            const tenant = await service.createTenant(name, description);
            selectTenant(tenant.id);
          }, onCreated);
        }}
      >
        <label className="field">
          Tenant name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            minLength={2}
            maxLength={60}
            placeholder="e.g. Research team"
            autoComplete="off"
          />
        </label>
        <label className="field">
          Description (optional)
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={160}
            placeholder="What will this tenant be used for?"
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <ActionButton type="button" className="button" onClick={onClose}>
            Cancel
          </ActionButton>
          <ActionButton className="button primary" disabled={busy}>
            Create tenant
          </ActionButton>
        </div>
      </form>
    </Modal>
  );
}
