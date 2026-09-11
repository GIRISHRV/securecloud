import {
  createContext,
  useContext,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { PortalService } from "../domain/models";
import { MockPortalService } from "../services/mockService";
import { ApiPortalService } from "../services/apiService";
const Context = createContext<{
  service: PortalService;
  tenantId: string;
  selectTenant: (id: string) => void;
} | null>(null);
function createBrowserService() {
  try {
    if (
      import.meta.env.VITE_USE_API === "true" ||
      (typeof window !== "undefined" &&
        (window as unknown as { __SECURECLOUD_USE_API__?: boolean })
          .__SECURECLOUD_USE_API__)
    ) {
      return new ApiPortalService();
    }
    return new MockPortalService(window.localStorage);
  } catch {
    return new MockPortalService();
  }
}
export function PortalProvider({ children }: { children: ReactNode }) {
  const [service] = useState(createBrowserService);
  const [tenantId, selectTenant] = useState("");
  return (
    <Context.Provider value={{ service, tenantId, selectTenant }}>
      {children}
    </Context.Provider>
  );
}
export function usePortal() {
  const context = useContext(Context);
  if (!context) throw new Error("PortalProvider missing");
  const { service, selectTenant } = context;
  const snapshot = useSyncExternalStore(service.subscribe, service.getSnapshot);
  const tenantId = snapshot.data.tenants.some((t) => t.id === context.tenantId)
    ? context.tenantId
    : "";
  const scopedData = !tenantId
    ? snapshot.data
    : {
        ...snapshot.data,
        tenants: snapshot.data.tenants.filter((t) => t.id === tenantId),
        workloads: snapshot.data.workloads.filter(
          (w) => w.tenantId === tenantId,
        ),
        traffic: snapshot.data.traffic.filter(
          (e) => e.sourceTenant === tenantId,
        ),
        incidents: snapshot.data.incidents.filter(
          (i) => i.tenantId === tenantId,
        ),
      };
  return { ...snapshot, service, scopedData, tenantId, selectTenant };
}
export function useAction() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>, success?: () => void) {
    setError("");
    setBusy(true);
    try {
      await action();
      success?.();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "The operation could not be completed.",
      );
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, run };
}
