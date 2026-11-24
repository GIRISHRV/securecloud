import { useMemo, useState } from "react";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Database, PackageOpen, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import type { AdminSnapshot } from "../adminService";
import MetricCard from "@/components/kokonutui/metric-card";
import { CATEGORIES, categoryRevenueSeries, dailySeries, dayOf, delta, periodComparison, STATUS_LABEL, STATUS_ORDER, statusCounts, topProducts } from "../analytics";
import { BarList, Sparkline } from "../charts";
import { Avatar, Empty, money, PageHead, Panel, relative, Status } from "../ui";
import type { AdminPage } from "../AdminApp";

const RANGES = [7, 14, 30] as const;

export function Dashboard({ data, navigate, refresh, onLoadSample, loadingSample }: {
  data: AdminSnapshot; navigate: (page: AdminPage, id?: string) => void; refresh: () => Promise<void>;
  onLoadSample: () => Promise<void>; loadingSample: boolean;
}) {
  const [range, setRange] = useState<(typeof RANGES)[number]>(14);
  const series = useMemo(() => dailySeries(data.orders, range), [data.orders, range]);
  const { current, previous } = useMemo(() => periodComparison(data.orders, range), [data.orders, range]);
  const top = useMemo(() => topProducts(data.orders, data.products, range).slice(0, 4), [data.orders, data.products, range]);
  const statuses = useMemo(() => statusCounts(data.orders), [data.orders]);
  const lowStock = data.products.filter((product) => product.stock_quantity <= 10).sort((a, b) => a.stock_quantity - b.stock_quantity);
  const needsAction = statuses.placed + statuses.processing;
  const activeIncidents = data.security.incidents.filter((incident) => incident.status !== "restored" && incident.status !== "closed");
  const blocked = data.security.traffic.filter((event) => event.decision === "denied").length;
  const latestRisk = data.security.risk[0];
  const revenueByCategory = useMemo(() => categoryRevenueSeries(data.orders, 60), [data.orders]);
  const incidentEvents = useMemo(() => data.security.incidents.map((incident) => ({
    date: dayOf(incident.createdAt), label: `Incident: ${incident.sourceName}`,
  })), [data.security.incidents]);

  return (
    <>
      <PageHead title="Store overview" description={`Northstar Retail · last ${range} days`}>
        <div className="ad-segment" role="group" aria-label="Date range">
          {RANGES.map((option) => (
            <button key={option} className={range === option ? "active" : ""} aria-pressed={range === option} onClick={() => setRange(option)}>{option}d</button>
          ))}
        </div>
        <button className="ad-button" onClick={() => void refresh()}><RefreshCw size={15} />Refresh</button>
      </PageHead>

      {activeIncidents.length > 0 && (
        <button className="ad-alert-banner" onClick={() => navigate("security")}>
          <ShieldAlert size={20} aria-hidden="true" />
          <span><strong>{activeIncidents.length} security incident{activeIncidents.length === 1 ? "" : "s"} need attention</strong>
            <small>SecureCloud has flagged {activeIncidents.map((incident) => incident.sourceName).join(", ")}. Review evidence and response options.</small></span>
          <span className="ad-alert-cta">Investigate</span>
        </button>
      )}

      {data.orders.length === 0 && (
        <Panel className="ad-onboarding">
          <div>
            <Database size={22} aria-hidden="true" />
            <div><strong>No orders yet</strong><p>Place an order in the storefront, or load the labelled sample catalogue and 30 days of sample orders to explore the dashboard.</p></div>
            <button className="ad-button ad-button-primary" disabled={loadingSample} onClick={() => void onLoadSample()}>{loadingSample ? "Loading…" : "Load sample data"}</button>
          </div>
        </Panel>
      )}

      <div className="ad-kpis">
        <Kpi label="Revenue" value={money(current.revenue)} change={delta(current.revenue, previous.revenue)} trend={series.map((point) => point.revenue)} />
        <Kpi label="Orders" value={String(current.orders)} change={delta(current.orders, previous.orders)} trend={series.map((point) => point.orders)} />
        <Kpi label="Average order value" value={money(current.aov)} change={delta(current.aov, previous.aov)} />
        <Kpi label="Customers who ordered" value={String(current.customers)} change={delta(current.customers, previous.customers)} footnote={`${data.overview.active_customers} online now`} />
      </div>

      <div className="ad-grid-main">
        <MetricCard className="ad-metric-card" label="Revenue" currency="INR" format="currency"
          segments={[...CATEGORIES]} data={revenueByCategory} events={incidentEvents}
          periods={[7, 14, 30]} defaultPeriod={30} />
        <Panel title="Fulfilment pipeline" subtitle={`${needsAction} order${needsAction === 1 ? "" : "s"} waiting for action`}
          action={<button className="ad-link" onClick={() => navigate("orders")}>Manage</button>}>
          <BarList items={STATUS_ORDER.map((status) => ({ key: status, label: <Status value={status} label={STATUS_LABEL[status]} />, value: statuses[status] }))} />
        </Panel>
      </div>

      <div className="ad-grid-3">
        <Panel title="Top products" subtitle={`By revenue, last ${range} days`} action={<button className="ad-link" onClick={() => navigate("products")}>All products</button>}>
          {top.length
            ? <ul className="ad-top-products">
                {top.map((product, index) => (
                  <li key={product.id}>
                    <span className="ad-rank">{index + 1}</span>
                    <span className="ad-thumb">{product.image ? <img src={product.image} alt="" /> : null}</span>
                    <span className="ad-top-name"><strong>{product.name}</strong><small>{product.units} sold</small></span>
                    <strong className="ad-num">{money(product.revenue)}</strong>
                  </li>
                ))}
              </ul>
            : <Empty title="No sales in this period" />}
        </Panel>

        <Panel title="Inventory alerts" subtitle="Products with 10 or fewer units">
          {lowStock.length
            ? <ul className="ad-stock-list">
                {lowStock.map((product) => (
                  <li key={product.id}>
                    <span className="ad-thumb">{product.image_path ? <img src={product.image_path} alt="" /> : null}</span>
                    <span className="ad-top-name"><strong>{product.name}</strong><small>{product.sku}</small></span>
                    <Status value={product.stock_quantity === 0 ? "failed" : "low"} label={product.stock_quantity === 0 ? "Out of stock" : `${product.stock_quantity} left`} />
                  </li>
                ))}
              </ul>
            : <Empty title="Stock levels are healthy"><PackageOpen size={18} aria-hidden="true" /></Empty>}
        </Panel>

        <Panel title="SecureCloud" subtitle="Zero-trust protection for this store" action={<button className="ad-link" onClick={() => navigate("security")}>Open</button>}>
          <div className={`ad-posture ${activeIncidents.length ? "warn" : "ok"}`}>
            {activeIncidents.length ? <AlertTriangle size={22} aria-hidden="true" /> : <ShieldCheck size={22} aria-hidden="true" />}
            <div><strong>{activeIncidents.length ? "Action required" : data.apiOnline ? "Protected" : "Status unavailable"}</strong>
              <small>{activeIncidents.length ? "An incident is open" : "No open incidents"}</small></div>
          </div>
          <dl className="ad-facts">
            <div><dt>Open incidents</dt><dd>{activeIncidents.length}</dd></div>
            <div><dt>Blocked connections</dt><dd>{blocked}</dd></div>
            <div><dt>Detector</dt><dd>{latestRisk?.modelVersion ?? "No scores yet"}</dd></div>
            <div><dt>Latest risk</dt><dd>{latestRisk ? `${latestRisk.accumulatedRisk.toFixed(2)} / ${latestRisk.threshold.toFixed(2)}` : "—"}</dd></div>
          </dl>
        </Panel>
      </div>

      <div className="ad-grid-main">
        <Panel title="Recent orders" action={<button className="ad-link" onClick={() => navigate("orders")}>View all</button>} flush>
          {data.orders.length
            ? <div className="ad-table-wrap"><table className="ad-table">
                <thead><tr><th>Order</th><th>Customer</th><th>Status</th><th className="ad-right">Total</th></tr></thead>
                <tbody>
                  {data.orders.slice(0, 6).map((order) => (
                    <tr key={order.id} className="ad-row-link" onClick={() => navigate("orders", order.id)}>
                      <td><button className="ad-cell-link" onClick={(event) => { event.stopPropagation(); navigate("orders", order.id); }}>{order.order_number}</button><small>{relative(order.created_at)}</small></td>
                      <td><span className="ad-person"><Avatar name={order.customer.name} /><span><span>{order.customer.name}</span><small>{order.delivery_address.city}</small></span></span></td>
                      <td><Status value={order.status} label={STATUS_LABEL[order.status]} /></td>
                      <td className="ad-right ad-num">{money(order.total_minor)}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            : <Empty title="No orders yet" />}
        </Panel>
        <Panel title="Live business activity" subtitle="Requests recorded by the retail API">
          {data.activity.length
            ? <ul className="ad-activity">
                {data.activity.slice(0, 7).map((item) => (
                  <li key={item.id}>
                    <span className={`ad-activity-dot ${["denied", "failed"].includes(item.result) ? "bad" : ""}`} />
                    <div><strong>{item.action.replaceAll(".", " ").replaceAll("_", " ")}</strong>
                      <small><code>{item.source_workload} → {item.destination_workload}</code> · {item.result}</small></div>
                    <time>{relative(item.occurred_at)}</time>
                  </li>
                ))}
              </ul>
            : <Empty title="No activity yet">Checkouts and order updates appear here as they happen.</Empty>}
        </Panel>
      </div>
    </>
  );
}

function Kpi({ label, value, change, trend, footnote }: { label: string; value: string; change: number | null; trend?: number[]; footnote?: string }) {
  const tone = change === null ? "new" : change > 0.005 ? "up" : change < -0.005 ? "down" : "flat";
  return (
    <div className="ad-kpi">
      <span className="ad-kpi-label">{label}</span>
      <strong className="ad-kpi-value">{value}</strong>
      <span className="ad-kpi-foot">
        <span className={`ad-delta ad-delta-${tone}`}>
          {tone === "up" && <ArrowUpRight size={14} aria-hidden="true" />}
          {tone === "down" && <ArrowDownRight size={14} aria-hidden="true" />}
          {change === null ? "New" : `${change > 0 ? "+" : ""}${(change * 100).toFixed(0)}%`}
        </span>
        <small>{footnote ?? "vs previous period"}</small>
      </span>
      {trend && <Sparkline values={trend} />}
    </div>
  );
}
