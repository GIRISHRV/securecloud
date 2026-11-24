import { Database, Globe, RefreshCw, Server, ShieldCheck } from "lucide-react";
import type { AdminSnapshot } from "../adminService";
import { PageHead, Panel, Status } from "../ui";

export function Services({ data, refresh }: { data: AdminSnapshot; refresh: () => Promise<void> }) {
  const services = [
    { icon: Globe, name: "Customer storefront", detail: "Registration, catalogue, cart, checkout and order tracking", online: true, meta: `${data.products.filter((product) => product.published).length} products live` },
    { icon: Server, name: "Retail API", detail: "Authenticated business operations and audit events", online: data.apiOnline, meta: `${data.activity.length} recent requests` },
    { icon: Database, name: "Retail database", detail: "Customers, catalogue, carts, orders and payments", online: data.apiOnline, meta: `${data.customers.length} customers · ${data.orders.length} orders` },
    { icon: ShieldCheck, name: "SecureCloud security plane", detail: "Network policy, Hubble telemetry, temporal-graph risk and incident response", online: data.apiOnline, meta: `${data.security.risk.length} risk windows scored` },
  ];
  return (
    <>
      <PageHead title="Protected services" description="Health of the services that make up the store. Infrastructure controls stay in the SecureCloud console.">
        <button className="ad-button" onClick={() => void refresh()}><RefreshCw size={15} />Refresh</button>
      </PageHead>
      <div className="ad-service-grid">
        {services.map(({ icon: Icon, name, detail, online, meta }) => (
          <Panel key={name}>
            <div className="ad-service">
              <span className="ad-service-icon"><Icon size={20} aria-hidden="true" /></span>
              <div><strong>{name}</strong><p>{detail}</p><small>{meta}</small></div>
              <Status value={online ? "online" : "unavailable"} label={online ? "Online" : "Unavailable"} />
            </div>
          </Panel>
        ))}
      </div>
    </>
  );
}
