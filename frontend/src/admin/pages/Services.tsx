import { useCallback, useEffect, useState } from "react";
import { Lock, Puzzle, RefreshCw, Server, Store } from "lucide-react";
import type { AdminService, PlatformService } from "../adminService";
import { PageHead, Panel, Status } from "../ui";

const GROUPS: Array<{ kind: PlatformService["kind"]; title: string; subtitle: string; icon: typeof Server }> = [
  { kind: "platform", title: "Shared platform services", subtitle: "Run by the provider. Only shop order APIs may call them.", icon: Server },
  { kind: "plugin", title: "Plugins", subtitle: "Third-party code installed by a shop. May call only what it was granted.", icon: Puzzle },
  { kind: "shop", title: "Shop services", subtitle: "Each shop's storefront, order API and database, isolated per tenant.", icon: Store },
];

export function Services({ service }: { service: AdminService }) {
  const [items, setItems] = useState<PlatformService[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { setItems(await service.platformServices()); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Services could not be loaded"); }
  }, [service]);
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 10_000); return () => window.clearInterval(timer); }, [load]);

  return (
    <>
      <PageHead title="Shared services & plugins" description="Everything running on the platform, who owns it, and which services it is allowed to call.">
        <button className="ad-button" onClick={() => void load()}><RefreshCw size={15} />Refresh</button>
      </PageHead>
      {error && <div className="ad-banner" role="alert"><strong>Could not load services.</strong><span>{error}</span></div>}
      {GROUPS.map(({ kind, title, subtitle, icon: Icon }) => (
        <Panel key={kind} title={title} subtitle={subtitle}>
          <div className="ad-service-grid">
            {(items ?? []).filter((item) => item.kind === kind).map((item) => (
              <div key={item.id} className="ad-service">
                <span className="ad-service-icon">{item.quarantined ? <Lock size={20} aria-hidden="true" /> : <Icon size={20} aria-hidden="true" />}</span>
                <div>
                  <strong>{item.name}</strong>
                  <p>{item.tenant}{kind === "plugin" ? " · installed plugin" : ""}</p>
                  <small>{item.calls.length ? `May call: ${item.calls.join(", ")}` : "Receives calls only"}</small>
                </div>
                <Status value={item.quarantined ? "quarantined" : item.status === "running" ? "online" : "unavailable"}
                  label={item.quarantined ? "Quarantined" : item.status === "running" ? "Running" : item.status} />
              </div>
            ))}
          </div>
        </Panel>
      ))}
    </>
  );
}
